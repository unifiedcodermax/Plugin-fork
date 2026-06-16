# frozen_string_literal: true

require_relative '../logger'
require_relative '../limits_cache'
require_relative '../geometry/quick_checks'

module Planara
  module Observers
    # Sketchup::EntitiesObserver that fires during active tool gestures
    # (Push/Pull, Move, Scale) to provide real-time violation feedback.
    #
    # Unlike LiveValidator (which fires on transaction commit, i.e.
    # *after* the user releases the mouse), this observer fires on
    # onElementModified — *during* the drag — and performs lightweight
    # Ruby-side checks against cached limits from the last engine
    # response.
    #
    # Performance safeguards:
    #   1. Only processes Group/ComponentInstance changes (ignores
    #      individual edges/faces).
    #   2. 100ms trailing-edge debounce collapses rapid-fire events.
    #   3. Short-circuits when the computed height hasn't changed.
    #   4. No HTTP calls — all checks are Ruby-side bounding-box math.
    class InDesignObserver < Sketchup::EntitiesObserver
      DEBOUNCE_S = 0.1  # 100ms — fast enough for visual feedback

      def initialize
        super()
        @timer_id = nil
        @last_height = nil
        @last_floor_warnings = {}
      end

      # Fires during active tool gestures — the geometry has changed
      # but the operation hasn't committed yet.
      def onElementModified(entities, entity)
        return unless relevant_entity?(entity)
        schedule
      end

      def onElementAdded(entities, entity)
        return unless relevant_entity?(entity)
        schedule
      end

      def onElementRemoved(entities, entity_id)
        # entity_id is an integer (persistent_id) for removed entities.
        # Can't filter by type here — schedule unconditionally but let
        # the debounced callback handle the check.
        schedule
      end

      # Detach from the entities collection. Idempotent.
      def detach(model)
        model.entities.remove_observer(self) if model
      rescue StandardError
        nil
      ensure
        cancel_timer
        @last_height = nil
        @last_floor_warnings = {}
      end

      private

      # Only process groups and component instances — these are the
      # floor/plot containers. Ignore individual edges, faces, etc.
      # to avoid flooding during Push/Pull on sub-geometry.
      def relevant_entity?(entity)
        entity.is_a?(Sketchup::Group) || entity.is_a?(Sketchup::ComponentInstance)
      end

      def schedule
        cancel_timer
        @timer_id = ::UI.start_timer(DEBOUNCE_S, false) do
          @timer_id = nil
          begin
            evaluate
          rescue StandardError => e
            Planara::Logger.error(
              'in_design_observer_error',
              error: e.message,
              backtrace: e.backtrace&.first(3)
            )
          end
        end
      end

      def cancel_timer
        return unless @timer_id
        ::UI.stop_timer(@timer_id) rescue nil
        @timer_id = nil
      end

      def evaluate
        model = Sketchup.active_model
        return unless model

        warnings = []

        # -- Building height check --
        check_building_height(model, warnings)

        # -- Per-floor room height check --
        check_room_heights(model, warnings)

        # Push to UI
        if warnings.any?
          Planara::UI::ResultsDialog.update_in_design_warning(warnings)
          # Also set status bar for glanceable feedback
          first = warnings.first
          ::Sketchup.set_status_text(
            "\u26A0 #{first[:message]}",
            SB_PROMPT
          )
        else
          Planara::UI::ResultsDialog.clear_in_design_warning
          ::Sketchup.set_status_text('', SB_PROMPT)
        end
      end

      def check_building_height(model, warnings)
        limit_info = LimitsCache.max_height
        return unless limit_info

        max_h = limit_info[:value]
        return unless max_h && max_h > 0 && max_h < 999 # skip info-only rules with 999m

        height = Geometry::QuickChecks.total_building_height(model)

        # Short-circuit if height hasn't changed
        if @last_height && (height - @last_height).abs < 0.001
          return
        end
        @last_height = height

        if height > max_h
          warnings << {
            type: 'height',
            message: "Height #{height.round(1)}m exceeds limit #{max_h.round(1)}m",
            detail: "Building height: #{height.round(2)}m | Maximum allowed: #{max_h.round(1)}m",
            source: limit_info[:label] || 'Height Limit',
            current: height.round(2),
            limit: max_h
          }
        end
      end

      def check_room_heights(model, warnings)
        limit_info = LimitsCache.min_room_height
        return unless limit_info

        min_h = limit_info[:value]
        return unless min_h && min_h > 0

        floor_heights = Geometry::QuickChecks.floor_heights(model)
        new_floor_warnings = {}

        floor_heights.each do |level, height_m|
          next if level < 0 # skip basements

          if height_m < min_h - 0.005 # same tolerance as engine
            new_floor_warnings[level] = height_m
            warnings << {
              type: 'room_height',
              message: "Floor #{level} height #{height_m.round(2)}m below minimum #{min_h.round(2)}m",
              detail: "Floor #{level}: #{height_m.round(2)}m | Minimum required: #{min_h.round(2)}m",
              source: limit_info[:label] || 'Room Height Minimum',
              current: height_m.round(2),
              limit: min_h
            }
          end
        end

        @last_floor_warnings = new_floor_warnings
      end
    end
  end
end
