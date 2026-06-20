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

        min_bottom_m = nil
        max_top_m = nil

        each_floor_entity(model) do |level, e|
          next if level < 0 # exclude basements

          bb = e.bounds
          height_m = Units.inches_to_meters(bb.max.z - bb.min.z)
          height_m = 3.0 if height_m <= 0.0 # degenerate fallback

          bottom_m = Units.inches_to_meters(bb.min.z)
          top_m = bottom_m + height_m

          min_bottom_m = bottom_m if min_bottom_m.nil? || bottom_m < min_bottom_m
          max_top_m = top_m if max_top_m.nil? || top_m > max_top_m
        end

        return 0.0 unless min_bottom_m && max_top_m && max_top_m > min_bottom_m
        (max_top_m - min_bottom_m).round(3)
      end

      # Per-floor heights in meters.
      #
      # @param model [Sketchup::Model]
      # @return [Hash{Integer => Float}] { level => height_m }
      def floor_heights(model)
        return {} unless model

        result = {}
        each_floor_entity(model) do |level, e|
          bb = e.bounds
          height_m = Units.inches_to_meters(bb.max.z - bb.min.z)
          height_m = 3.0 if height_m <= 0.0 # degenerate fallback
          result[level] = height_m.round(3)
        end
        result
      end

      # Approximate FSI calculation using bounding boxes.
      # Uses horizontal footprint of plot and above-grade floors.
      #
      # @param model [Sketchup::Model]
      # @return [Float, nil] approximate FSI, or nil if plot not found
      def approximate_fsi(model)
        return nil unless model

        plot_area_sqm = 0.0
        built_up_sqm = 0.0

        plot_entity = find_plot_entity(model)
        if plot_entity
          bb = plot_entity.bounds
          width_m = Units.inches_to_meters(bb.width)
          depth_m = Units.inches_to_meters(bb.depth)
          plot_area_sqm = width_m * depth_m
        end

        each_floor_entity(model) do |level, e|
          next if level < 0 # ignore basements for FSI

          bb = e.bounds
          width_m = Units.inches_to_meters(bb.width)
          depth_m = Units.inches_to_meters(bb.depth)
          built_up_sqm += (width_m * depth_m)
        end

        return nil if plot_area_sqm <= 0.0
        (built_up_sqm / plot_area_sqm).round(2)
      end

      # Approximate setback check using bounding-box edge distances.
      #
      # For each above-grade floor, computes the minimum axis-aligned
      # distance between the floor's bounding box and the plot's
      # bounding box edges.  This is an approximation:
      #   - Exact for rectangular plots and rectangular footprints
      #   - Conservative (under-estimates distance) for irregular shapes
      #
      # @param model [Sketchup::Model]
      # @return [Hash, nil] { min_distance_m:, worst_level:, per_floor: [{level:, distance_m:}] }
      #   or nil if no plot/floors found
      def approximate_setback(model)
        return nil unless model

        plot_entity = find_plot_entity(model)
        return nil unless plot_entity

        plot_bb = plot_entity.bounds
        plot_min_x = Units.inches_to_meters(plot_bb.min.x)
        plot_max_x = Units.inches_to_meters(plot_bb.max.x)
        plot_min_y = Units.inches_to_meters(plot_bb.min.y)
        plot_max_y = Units.inches_to_meters(plot_bb.max.y)

        worst_distance = nil
        worst_level = nil
        per_floor = []

        each_floor_entity(model) do |level, entity|
          next if level < 0 # skip basements

          bb = entity.bounds
          floor_min_x = Units.inches_to_meters(bb.min.x)
          floor_max_x = Units.inches_to_meters(bb.max.x)
          floor_min_y = Units.inches_to_meters(bb.min.y)
          floor_max_y = Units.inches_to_meters(bb.max.y)

          # Distance from each floor edge to the nearest plot edge
          dist_left   = floor_min_x - plot_min_x
          dist_right  = plot_max_x - floor_max_x
          dist_front  = floor_min_y - plot_min_y
          dist_back   = plot_max_y - floor_max_y

          min_dist = [dist_left, dist_right, dist_front, dist_back].min
          per_floor << { level: level, distance_m: min_dist.round(3) }

          if worst_distance.nil? || min_dist < worst_distance
            worst_distance = min_dist
            worst_level = level
          end
        end

        return nil if per_floor.empty? || worst_distance.nil?

        {
          min_distance_m: worst_distance.round(3),
          worst_level: worst_level,
          per_floor: per_floor
        }
      end

      # Approximate ground coverage percentage using bounding boxes.
      #
      # Uses the sum of individual ground-floor bounding box areas
      # (not one combined BB) to avoid overestimation when the design
      # has multiple detached ground-level structures.
      #
      # @param model [Sketchup::Model]
      # @return [Float, nil] approximate coverage percentage, or nil if no plot
      def approximate_coverage(model)
        return nil unless model

        plot_entity = find_plot_entity(model)
        return nil unless plot_entity

        plot_bb = plot_entity.bounds
        plot_area_sqm = Units.inches_to_meters(plot_bb.width) * Units.inches_to_meters(plot_bb.depth)
        return nil if plot_area_sqm <= 0.0

        ground_area_sqm = 0.0

        each_floor_entity(model) do |level, e|
          next unless level == 0 # only ground floor(s) count

          bb = e.bounds
          width_m = Units.inches_to_meters(bb.width)
          depth_m = Units.inches_to_meters(bb.depth)
          ground_area_sqm += (width_m * depth_m)
        end

        ((ground_area_sqm / plot_area_sqm) * 100.0).round(2)
      end

      # -- single-entity queries (for entity-scoped Live Check) -----------------

      # Height for a single floor entity in meters.
      #
      # @param entity [Sketchup::Group, Sketchup::ComponentInstance]
      # @return [Float] height in meters (falls back to 3.0 for degenerate geometry)
      def single_floor_height(entity)
        bb = entity.bounds
        height_m = Units.inches_to_meters(bb.max.z - bb.min.z)
        height_m <= 0.0 ? 3.0 : height_m.round(3)
      end

      # Minimum axis-aligned setback distance for a single floor entity
      # against the plot boundary.
      #
      # @param model [Sketchup::Model]
      # @param entity [Sketchup::Group, Sketchup::ComponentInstance]
      # @return [Float, nil] minimum distance in meters, or nil if no plot found
      def single_floor_setback(model, entity)
        plot_entity = find_plot_entity(model)
        return nil unless plot_entity

        plot_bb = plot_entity.bounds
        plot_min_x = Units.inches_to_meters(plot_bb.min.x)
        plot_max_x = Units.inches_to_meters(plot_bb.max.x)
        plot_min_y = Units.inches_to_meters(plot_bb.min.y)
        plot_max_y = Units.inches_to_meters(plot_bb.max.y)

        bb = entity.bounds
        floor_min_x = Units.inches_to_meters(bb.min.x)
        floor_max_x = Units.inches_to_meters(bb.max.x)
        floor_min_y = Units.inches_to_meters(bb.min.y)
        floor_max_y = Units.inches_to_meters(bb.max.y)

        dist_left   = floor_min_x - plot_min_x
        dist_right  = plot_max_x - floor_max_x
        dist_front  = floor_min_y - plot_min_y
        dist_back   = plot_max_y - floor_max_y

        [dist_left, dist_right, dist_front, dist_back].min.round(3)
      end

      # -- entity discovery helpers --------------------------------------------
      #
      # CRITICAL: Only yield entities that are UNIQUELY named "Floor N".
      # In SketchUp, multiple ComponentInstances can share the same
      # definition name (e.g. "Floor 0"). When the user copies a floor
      # group, SketchUp may create many instances whose definition.name
      # all match the pattern but whose instance.name is empty.
      #
      # The extractor's `find_floors` uses `entity_name()` which falls
      # back to definition.name. This works for extraction (it grabs
      # them all). But for quick checks during live editing, we must
      # de-duplicate: for each floor level N, we yield ONLY ONE entity
      # (the first found). This prevents phantom duplicates from
      # polluting setback/height/coverage calculations.
      #
      # Additionally, we only consider Groups. ComponentInstances
      # often represent furniture, windows, doors, etc. whose
      # definition names may coincidentally match "Floor N". True
      # floor containers in Planara models are always Groups (created
      # by the fallback auto-discovery or named by the user).

      # Yields [level, entity] for each unique floor level found.
      # Only considers Groups (not ComponentInstances) to avoid
      # picking up decorative components that share a floor definition.
      def each_floor_entity(model)
        seen_levels = {}

        model.entities.each do |e|
          # Only top-level Groups are floor containers.
          # ComponentInstances of floor definitions are copies/debris.
          next unless e.is_a?(Sketchup::Group)

          name = e.name.to_s.strip
          match = FLOOR_NAME_REGEX.match(name)
          next unless match

          level = match[1].to_i
          # De-duplicate: first entity for each level wins.
          next if seen_levels.key?(level)

          seen_levels[level] = true
          yield level, e
        end
      end

      # Find the Plot entity (Group or ComponentInstance named "Plot").
      def find_plot_entity(model)
        model.entities.find do |e|
          next unless e.is_a?(Sketchup::Group) || e.is_a?(Sketchup::ComponentInstance)
          name = entity_name(e)
          name =~ PLOT_NAME_REGEX
        end
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
