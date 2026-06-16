# frozen_string_literal: true

require_relative 'units'

module Planara
  module Geometry
    # Lightweight geometry queries for the in-design observer.
    #
    # These run in < 1ms by reading SketchUp bounding boxes directly
    # instead of doing polygon extraction. They are intentionally
    # approximate — the full engine validation gives exact numbers.
    #
    # Used by InDesignObserver during active tool gestures (Push/Pull,
    # Move, Scale) where sub-100ms latency is required.
    module QuickChecks
      FLOOR_NAME_REGEX = /^floor\s*(-?\d+)$/i.freeze
      PLOT_NAME_REGEX  = /^plot$/i.freeze

      module_function

      # Total building height in meters: sum of above-grade floor
      # bounding box heights. Matches the engine's height.py logic
      # which sums floor.height_m for level >= 0.
      #
      # @param model [Sketchup::Model]
      # @return [Float] total height in meters, 0.0 if no floors found
      def total_building_height(model)
        return 0.0 unless model

        total = 0.0
        model.entities.each do |e|
          next unless e.is_a?(Sketchup::Group) || e.is_a?(Sketchup::ComponentInstance)
          name = entity_name(e)
          match = FLOOR_NAME_REGEX.match(name)
          next unless match

          level = match[1].to_i
          next if level < 0 # exclude basements

          bb = e.bounds
          height_in = bb.max.z - bb.min.z
          height_m = Units.inches_to_meters(height_in)
          total += height_m > 0 ? height_m : 0.0
        end
        total
      end

      # Per-floor heights in meters.
      #
      # @param model [Sketchup::Model]
      # @return [Hash{Integer => Float}] { level => height_m }
      def floor_heights(model)
        return {} unless model

        result = {}
        model.entities.each do |e|
          next unless e.is_a?(Sketchup::Group) || e.is_a?(Sketchup::ComponentInstance)
          name = entity_name(e)
          match = FLOOR_NAME_REGEX.match(name)
          next unless match

          level = match[1].to_i
          bb = e.bounds
          height_in = bb.max.z - bb.min.z
          height_m = Units.inches_to_meters(height_in)
          result[level] = (height_m > 0 ? height_m : 0.0).round(3)
        end
        result
      end

      # -- helpers ---------------------------------------------------------------

      def entity_name(entity)
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
