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
    #   1. 100ms trailing-edge debounce collapses rapid-fire events.
    #   2. No HTTP calls — all checks are Ruby-side bounding-box math.
    #
    # Entity-scoped Live Check:
    #   Live Check shows violations ONLY for the currently selected
    #   SketchUp entity. If the selection is a nested element (face,
    #   edge, sub-group inside a Floor group), it walks up the parent
    #   hierarchy to resolve to the containing tracked entity (Floor
    #   group). Building-wide checks (height, FSI, coverage) never
    #   appear in Live Check — they belong to Live Compliance.
    #
    # Violation payload schema (standardized):
    #   {
    #     type:        String   — category key (room_height, setback)
    #     severity:    String   — "warning"
    #     current:     Float    — the measured value
    #     limit:       Float    — the bylaw limit
    #     excess:      Float    — how much the limit is exceeded by (always positive when violated)
    #     unit:        String   — unit label ("m", etc.)
    #     source:      String   — provenance label, e.g. "Room Height Minimum (Live)"
    #     message:     String   — human-readable summary
    #     detail:      String   — secondary line with exact measurements
    #     entity_id:   Integer  — persistent_id of the SketchUp entity this violation belongs to
    #   }
    class InDesignObserver < Sketchup::EntitiesObserver
      DEBOUNCE_S = 0.1  # 100ms — fast enough for visual feedback

      def initialize
        super()
        @timer_id = nil
        @last_warnings = []     # cache last live_check warnings for persistence
      end

      # Fires during active tool gestures — the geometry has changed
      # but the operation hasn't committed yet.
      def onElementModified(entities, entity)
        schedule
      end

      def onElementAdded(entities, entity)
        schedule
      end

      def onElementRemoved(entities, entity_id)
        schedule
      end

      # Detach from the entities collection. Idempotent.
      def detach(model)
        model.entities.remove_observer(self) if model
      rescue StandardError
        nil
      ensure
        cancel_timer
        @last_warnings = []
      end

      # Allow external code to read the last warnings (e.g. to
      # re-push them after engine result clears the banner).
      def last_warnings
        @last_warnings
      end

      # Called by SelectionListener when the selection changes.
      # Triggers a debounced re-evaluation.
      def schedule_evaluate
        schedule
      end

      # Create a SelectionListener attached to this observer.
      # The listener forwards selection events to schedule_evaluate.
      def create_selection_listener
        SelectionListener.new(self)
      end

      # -- SelectionListener ---------------------------------------------------

      # Lightweight observer that fires when the user clicks a
      # different entity or clears the selection. Forwards the
      # event to InDesignObserver so it re-evaluates Live Check
      # for the newly selected entity.
      class SelectionListener < Sketchup::SelectionObserver
        def initialize(parent)
          super()
          @parent = parent
        end

        def onSelectionBulkChange(_selection)
          @parent.schedule_evaluate
        end

        def onSelectionCleared(_selection)
          @parent.schedule_evaluate
        end
      end

      private

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

        # Determine what the user is interacting with:
        # 1. Explicitly selected entity
        # 2. The group/component the user is editing inside (active_path)
        target = model.selection.first
        target ||= model.active_path.last if model.active_path && !model.active_path.empty?

        # Nothing selected and not inside a group → show prompt
        unless target
          Planara::UI::ResultsDialog.show_no_selection
          @last_warnings = []
          ::Sketchup.set_status_text('', SB_PROMPT)
          return
        end

        # Resolve to a tracked container (walk up to find the Floor group)
        resolved_info = resolve_to_tracked_container(model, target)

        unless resolved_info
          # Selected entity is not inside any tracked container
          Planara::UI::ResultsDialog.show_no_violations_for_selection
          @last_warnings = []
          ::Sketchup.set_status_text('', SB_PROMPT)
          return
        end

        live_check = []

        if resolved_info[:type] == :floor
          entity = resolved_info[:entity]
          level  = resolved_info[:level]

          check_single_floor_room_height(entity, level, live_check)
          check_single_floor_setback(model, entity, level, live_check)
        end

        @last_warnings = live_check

        if live_check.any?
          Planara::UI::ResultsDialog.update_in_design_warning(live_check)
          first = live_check.first
          ::Sketchup.set_status_text(
            "\u26A0 #{first[:message]}",
            SB_PROMPT
          )
        else
          Planara::UI::ResultsDialog.show_no_violations_for_selection
          ::Sketchup.set_status_text('', SB_PROMPT)
        end
      end

      # -- Hierarchy resolution ------------------------------------------------

      # Walk up from ``entity`` through its parent chain looking for a
      # tracked container (currently: Floor groups). Uses persistent_id
      # matching — no name-based type inference.
      #
      # @param model [Sketchup::Model]
      # @param entity [Sketchup::Entity] the selected or active-path entity
      # @return [Hash, nil] { type: :floor, entity:, level: } or nil
      def resolve_to_tracked_container(model, entity)
        # Build lookup of tracked entities by persistent_id
        tracked = {}
        Geometry::QuickChecks.each_floor_entity(model) do |level, floor_entity|
          tracked[floor_entity.persistent_id] = {
            type: :floor,
            entity: floor_entity,
            level: level
          }
        end

        # Walk up from the target entity
        current = entity
        while current && !current.is_a?(Sketchup::Model)
          # Check if this entity itself is tracked
          if current.respond_to?(:persistent_id) && tracked.key?(current.persistent_id)
            return tracked[current.persistent_id]
          end

          # Move up the hierarchy
          parent = current.respond_to?(:parent) ? current.parent : nil

          if parent.is_a?(Sketchup::ComponentDefinition)
            # The parent is a definition — we need the instance.
            # Prefer the active_path to find the correct instance
            # (handles multi-instance definitions correctly).
            parent_instance = nil
            if model.active_path
              model.active_path.each_with_index do |path_entity, idx|
                if path_entity.respond_to?(:definition) &&
                   path_entity.definition == parent
                  parent_instance = path_entity
                  break
                end
              end
            end
            # Fallback: first instance (correct for single-instance floors)
            parent_instance ||= parent.instances.first
            current = parent_instance
          elsif parent.is_a?(Sketchup::Entities)
            # parent is an Entities collection — its parent is the
            # Model or a ComponentDefinition
            owner = parent.parent
            if owner.is_a?(Sketchup::ComponentDefinition)
              parent_instance = nil
              if model.active_path
                model.active_path.each do |path_entity|
                  if path_entity.respond_to?(:definition) &&
                     path_entity.definition == owner
                    parent_instance = path_entity
                    break
                  end
                end
              end
              parent_instance ||= owner.instances.first
              current = parent_instance
            else
              # Owner is the Model — we've reached the top
              current = nil
            end
          else
            current = nil
          end
        end

        nil
      end

      # -- Standardized violation builder ------------------------------------

      # Build a warning for "below minimum" violations (room height, setback).
      def build_below_warning(type:, current:, limit:, unit:, source:, detail: nil, entity_id: nil)
        deficit = (limit - current).abs.round(2)
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
          detail: detail,
          entity_id: entity_id
        }
      end

      def humanize_type(type)
        case type
        when 'room_height' then 'Room height'
        when 'setback' then 'Setback'
        else type.to_s.gsub('_', ' ').capitalize
        end
      end

      # -- Targeted single-entity checks ---------------------------------------

      # Check room height for a single floor entity.
      #
      # @param entity [Sketchup::Group] the floor group
      # @param level [Integer] the floor level
      # @param warnings [Array<Hash>] violations are appended here
      def check_single_floor_room_height(entity, level, warnings)
        return if level < 0 # skip basements

        limit_info = LimitsCache.min_room_height
        return unless limit_info

        min_h = limit_info[:value]
        return unless min_h && min_h > 0

        height_m = Geometry::QuickChecks.single_floor_height(entity)

        if height_m < min_h - 0.005 # same tolerance as engine
          warnings << build_below_warning(
            type: 'room_height',
            current: height_m,
            limit: min_h,
            unit: 'm',
            source: limit_info[:label] || 'Room Height Minimum',
            detail: "Floor #{level}: #{height_m.round(2)}m | Min required: #{min_h.round(2)}m",
            entity_id: entity.persistent_id
          )
        end
      end

      # Check setback for a single floor entity.
      #
      # @param model [Sketchup::Model]
      # @param entity [Sketchup::Group] the floor group
      # @param level [Integer] the floor level
      # @param warnings [Array<Hash>] violations are appended here
      def check_single_floor_setback(model, entity, level, warnings)
        return if level < 0 # skip basements

        limit_info = LimitsCache.min_setback
        return unless limit_info

        min_setback = limit_info[:value]
        return unless min_setback && min_setback > 0

        distance = Geometry::QuickChecks.single_floor_setback(model, entity)
        return unless distance

        if distance < min_setback - 0.005
          warnings << build_below_warning(
            type: 'setback',
            current: distance,
            limit: min_setback,
            unit: 'm',
            source: limit_info[:label] || 'Setback Minimum',
            detail: "Floor #{level}: #{distance.round(2)}m from boundary | Required: #{min_setback.round(2)}m",
            entity_id: entity.persistent_id
          )
        end
      end

      # Safe entity name extraction for both Groups and ComponentInstances.
      def live_entity_name(entity)
        case entity
        when Sketchup::Group then entity.name.to_s.strip
        when Sketchup::ComponentInstance
          (entity.name && !entity.name.strip.empty? ? entity.name : entity.definition.name).to_s.strip
        else ''
        end
      end
    end
  end
end
