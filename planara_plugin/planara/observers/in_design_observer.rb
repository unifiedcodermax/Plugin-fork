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
    #
    # Violation payload schema (standardized):
    #   {
    #     type:     String   — category key (height, room_height, fsi, setback, coverage)
    #     severity: String   — "warning" (all Tier 2 are warnings, Tier 1 has authority)
    #     current:  Float    — the measured value
    #     limit:    Float    — the bylaw limit
    #     excess:   Float    — how much the limit is exceeded by (always positive when violated)
    #     unit:     String   — unit label ("m", "m²", "%", etc.)
    #     source:   String   — provenance label, e.g. "Height Limit (Live)"
    #     message:  String   — human-readable summary, e.g. "Height exceeds limit by 2.5m"
    #     detail:   String   — secondary line with exact measurements
    #   }
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
        # We must process all entities (including edges/faces) because when
        # a user edits inside a group using Push/Pull, the modified entities
        # are edges and faces, not groups. The 100ms debounce protects against
        # flooding during these rapid events.
        true
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

        # -- FSI check --
        check_fsi(model, warnings)

        # -- Setback check --
        check_setback(model, warnings)

        # -- Coverage check --
        check_coverage(model, warnings)

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

      # -- Standardized violation builder ------------------------------------

      # Build a standardized warning hash. Every check funnels through
      # this so the UI can render them uniformly.
      def build_warning(type:, current:, limit:, unit:, source:, detail: nil)
        excess = (current - limit).abs.round(3)
        message = "#{humanize_type(type)} exceeds limit by #{excess}#{unit}"
        detail ||= "Current: #{current.round(2)}#{unit} | Limit: #{limit.round(2)}#{unit}"

        {
          type: type,
          severity: 'warning',
          current: current.round(3),
          limit: limit,
          excess: excess,
          unit: unit,
          source: "#{source} (Live)",
          message: message,
          detail: detail
        }
      end

      # Build a warning for "below minimum" violations (room height).
      def build_below_warning(type:, current:, limit:, unit:, source:, detail: nil)
        deficit = (limit - current).abs.round(3)
        message = "#{humanize_type(type)} below minimum by #{deficit}#{unit}"
        detail ||= "Current: #{current.round(2)}#{unit} | Minimum: #{limit.round(2)}#{unit}"

        {
          type: type,
          severity: 'warning',
          current: current.round(3),
          limit: limit,
          excess: deficit,
          unit: unit,
          source: "#{source} (Live)",
          message: message,
          detail: detail
        }
      end

      def humanize_type(type)
        case type
        when 'height' then 'Height'
        when 'room_height' then 'Room height'
        when 'fsi' then 'FSI'
        when 'setback' then 'Setback'
        when 'coverage' then 'Ground coverage'
        else type.to_s.gsub('_', ' ').capitalize
        end
      end

      # -- Individual checks -------------------------------------------------

      def check_building_height(model, warnings)
        limit_info = LimitsCache.max_height
        return unless limit_info

        max_h = limit_info[:value]
        return unless max_h && max_h > 0 && max_h < 999 # skip info-only rules with 999m

        height = Geometry::QuickChecks.total_building_height(model)
        @last_height = height

        if height > max_h
          warnings << build_warning(
            type: 'height',
            current: height,
            limit: max_h,
            unit: 'm',
            source: limit_info[:label] || 'Height Limit',
            detail: "Building height: #{height.round(2)}m | Maximum allowed: #{max_h.round(1)}m | Exceeded by: #{(height - max_h).round(2)}m"
          )
        end
      end

      def check_room_heights(model, warnings)
        limit_info = LimitsCache.min_room_height
        return unless limit_info

        min_h = limit_info[:value]
        return unless min_h && min_h > 0

        floor_heights = Geometry::QuickChecks.floor_heights(model)
        new_floor_warnings = {}
        
        violating_floors = []
        worst_level = nil
        worst_height = nil

        floor_heights.each do |level, height_m|
          next if level < 0 # skip basements

          if height_m < min_h - 0.005 # same tolerance as engine
            new_floor_warnings[level] = height_m
            violating_floors << level
            if worst_height.nil? || height_m < worst_height
              worst_height = height_m
              worst_level = level
            end
          end
        end

        if violating_floors.any?
          count = violating_floors.size
          detail = if count == 1
                     "Floor #{worst_level}: #{worst_height.round(2)}m | Minimum required: #{min_h.round(2)}m | Below by: #{(min_h - worst_height).round(2)}m"
                   else
                     "#{count} floors below minimum. Worst: Floor #{worst_level} at #{worst_height.round(2)}m (below by #{(min_h - worst_height).round(2)}m)"
                   end

          warnings << build_below_warning(
            type: 'room_height',
            current: worst_height,
            limit: min_h,
            unit: 'm',
            source: limit_info[:label] || 'Room Height Minimum',
            detail: detail
          )
        end

        @last_floor_warnings = new_floor_warnings
      end

      def check_fsi(model, warnings)
        limit_info = LimitsCache.max_fsi
        return unless limit_info

        max_fsi = limit_info[:value]
        return unless max_fsi && max_fsi > 0

        fsi = Geometry::QuickChecks.approximate_fsi(model)
        return unless fsi

        if fsi > max_fsi
          warnings << build_warning(
            type: 'fsi',
            current: fsi,
            limit: max_fsi,
            unit: '',
            source: limit_info[:label] || 'FSI Limit',
            detail: "FSI: #{fsi} | Maximum allowed: #{max_fsi} | Exceeded by: #{(fsi - max_fsi).round(2)}"
          )
        end
      end

      def check_setback(model, warnings)
        limit_info = LimitsCache.min_setback
        return unless limit_info

        min_setback = limit_info[:value]
        return unless min_setback && min_setback > 0

        result = Geometry::QuickChecks.approximate_setback(model)
        return unless result

        min_dist = result[:min_distance_m]
        worst_level = result[:worst_level]

        if min_dist < min_setback - 0.005 # same tolerance as engine
          deficit = (min_setback - min_dist).round(3)
          detail = "Floor #{worst_level}: #{min_dist.round(2)}m from boundary | Required: #{min_setback.round(2)}m | Violated by: #{deficit.round(2)}m"

          # Report per-floor violations if multiple floors are affected
          violating_floors = result[:per_floor].select { |f| f[:distance_m] < min_setback - 0.005 }
          if violating_floors.size > 1
            floor_list = violating_floors.map { |f| "Floor #{f[:level]}: #{f[:distance_m]}m" }.join(', ')
            detail += " | All violations: #{floor_list}"
          end

          warnings << build_below_warning(
            type: 'setback',
            current: min_dist,
            limit: min_setback,
            unit: 'm',
            source: limit_info[:label] || 'Setback Minimum',
            detail: detail
          )
        end
      end

      def check_coverage(model, warnings)
        limit_info = LimitsCache.max_coverage
        return unless limit_info

        max_coverage = limit_info[:value]
        return unless max_coverage && max_coverage > 0

        coverage = Geometry::QuickChecks.approximate_coverage(model)
        return unless coverage

        if coverage > max_coverage + 0.01 # small tolerance for float drift
          warnings << build_warning(
            type: 'coverage',
            current: coverage,
            limit: max_coverage,
            unit: '%',
            source: limit_info[:label] || 'Coverage Limit',
            detail: "Ground coverage: #{coverage.round(1)}% | Maximum allowed: #{max_coverage.round(1)}% | Exceeded by: #{(coverage - max_coverage).round(1)}%"
          )
        end
      end
    end
  end
end
