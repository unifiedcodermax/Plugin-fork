# frozen_string_literal: true

require 'securerandom'

require_relative 'units'
require_relative '../logger'

module Planara
  module Geometry
    # Extracts a Snapshot payload from the active SketchUp model.
    #
    # Discovery rules:
    #
    #   PLOT  (two-pass)
    #     1. STRICT — top-level Group/ComponentInstance named /^plot$/i.
    #     2. FALLBACK — the top-level group containing the largest
    #        horizontal face at Z ≈ 0.  When fallback fires, the
    #        group is auto-renamed "Plot" so subsequent runs use
    #        the fast path.
    #
    #   FLOORS  (two-pass)
    #     1. STRICT — groups named "Floor N" (case-insensitive).
    #     2. FALLBACK — top-level groups (excluding the plot) that
    #        contain at least one horizontal face.  Sorted by the
    #        minimum Z of their bounding box; levels assigned 0, 1,
    #        2, …  Each is auto-renamed "Floor N".
    #
    # Auto-renaming is wrapped inside the model's existing undo
    # context (if one is active) or a new "Planara auto-detect"
    # operation, so the user can Undo if the heuristic grabbed
    # the wrong geometry.
    module Extractor
      class ExtractionError < StandardError; end

      FLOOR_NAME_REGEX = /^floor\s*(-?\d+)$/i.freeze
      PLOT_NAME_REGEX  = /^plot$/i.freeze

      # Wire-format version the plugin emits. The engine accepts and
      # warns on mismatch; bump alongside any non-additive change.
      SCHEMA_VERSION = '1.0'

      # Z-tolerance for "at ground level" in inches.  Faces whose
      # min-Z is within this value of 0 are considered ground-level.
      GROUND_Z_TOLERANCE_IN = 1.0

      module_function

      # Build a Snapshot payload from the active model.
      #
      # @param model [Sketchup::Model]
      # @param project [Hash] { city:, classification:, zone:, overlays: }.
      #   overlays defaults to [] when missing. Symbol keys.
      # @param parking_slots [Integer] number of slots the user reports
      #   the design provides. Surfaced to the parking evaluator.
      # @return [Hash] the JSON-ready Snapshot payload.
      def extract(model:, project:, parking_slots: 0)
        raise ExtractionError, 'no active model' unless model

        plot = find_plot(model) || find_plot_fallback(model)
        raise ExtractionError, 'no plot found — name a group "Plot" or draw a closed ground-level polygon inside a group' unless plot

        used_fallback_floors = false
        floors = find_floors(model)
        if floors.empty?
          floors = find_floors_fallback(model, plot)
          used_fallback_floors = true
        end
        raise ExtractionError, 'no floors found — name groups "Floor 0", "Floor 1", … or create groups with horizontal faces above the plot' if floors.empty?

        plot_polygon = polygon_from(plot)
        raise ExtractionError, 'plot has no horizontal face' unless plot_polygon

        floor_payloads = floors.map { |level, entity| floor_payload(level, entity) }.compact

        # Compute total above-grade building height using actual extracted floor heights.
        # This prevents double-counting overlaps (which sum(height) does) while
        # still respecting degenerate floor fallbacks (which raw bounds do not).
        above_grade = floors.select { |level, _| level >= 0 }
        total_height_m = nil
        if above_grade.any?
          min_bottom_m = nil
          max_top_m = nil

          above_grade.each do |level, entity|
            payload = floor_payloads.find { |p| p[:level] == level }
            next unless payload

            bottom_m = Units.inches_to_meters(entity.bounds.min.z)
            top_m = bottom_m + payload[:height_m]

            min_bottom_m = bottom_m if min_bottom_m.nil? || bottom_m < min_bottom_m
            max_top_m = top_m if max_top_m.nil? || top_m > max_top_m
          end

          if min_bottom_m && max_top_m && max_top_m > min_bottom_m
            total_height_m = (max_top_m - min_bottom_m).round(3)
          end
        end

        has_lift = (project || {})[:has_lift] || (project || {})['has_lift'] || false
        declared_floors = (project || {})[:declared_floors] || (project || {})['declared_floors']

        build_payload(
          plot_polygon: plot_polygon,
          floor_payloads: floor_payloads,
          project: project,
          parking_slots: parking_slots,
          has_lift: has_lift,
          declared_floors: declared_floors,
          total_height_m: total_height_m,
          used_fallback_floors: used_fallback_floors
        )
      end

      # Pure data assembly — no SketchUp references. Lives outside
      # `extract` so it can be exercised by `test/test_extractor.rb`
      # outside the SketchUp host. The shape pinned here IS the
      # Ruby↔Python wire contract.
      def build_payload(plot_polygon:, floor_payloads:, project:, parking_slots: 0, has_lift: false, declared_floors: nil, total_height_m: nil, used_fallback_floors: false)
        {
          schema_version: SCHEMA_VERSION,
          snapshot_id: SecureRandom.uuid,
          project: normalize_project(project),
          plot: {
            polygon: { exterior: plot_polygon[:exterior] },
            area_m2: plot_polygon[:area_m2],
          },
          building: {
            floors: floor_payloads,
            parking_slots_provided: parking_slots.to_i,
            has_lift: has_lift,
          }.tap do |b|
            b[:declared_floors] = declared_floors if declared_floors
            b[:total_height_m] = total_height_m if total_height_m
            b[:_used_fallback_floors] = true if used_fallback_floors
          end,
        }
      end

      # Coerce loose project hashes (symbol or string keys, missing
      # overlays) into the canonical shape the engine expects. Keeps
      # the rest of the plugin from caring about which form Session
      # or a dialog handed us.
      def normalize_project(project)
        h = project || {}
        get = ->(k) { h[k] || h[k.to_s] }
        overlays = get.call(:overlays) || []
        overlays = overlays.to_a.map(&:to_s).map(&:strip).reject(&:empty?)
        {
          city: get.call(:city).to_s,
          classification: get.call(:classification).to_s,
          zone: get.call(:zone).to_s,
          overlays: overlays,
        }
      end

      # -- strict discovery ----------------------------------------------------

      def find_plot(model)
        model.entities.find do |e|
          (e.is_a?(Sketchup::Group) || e.is_a?(Sketchup::ComponentInstance)) &&
            e.valid? &&
            entity_name(e) =~ PLOT_NAME_REGEX
        end
      end

      def find_floors(model)
        out = []
        model.entities.each do |e|
          next unless e.is_a?(Sketchup::Group) || e.is_a?(Sketchup::ComponentInstance)
          next unless e.valid?
          name = entity_name(e)
          if (match = FLOOR_NAME_REGEX.match(name))
            out << [match[1].to_i, e]
          end
        end
        out.sort_by!(&:first)
        out
      end

      # -- fallback discovery --------------------------------------------------

      # Find the top-level group/component with the largest horizontal
      # face at ground level (Z ≈ 0).  Auto-renames it "Plot".
      def find_plot_fallback(model)
        candidates = top_level_groups(model)
        best = nil
        best_area = 0

        candidates.each do |entity|
          faces = inner_entities(entity).grep(Sketchup::Face)
          horiz = faces.select { |f| horizontal?(f) }
          horiz.each do |face|
            # Check the face is at ground level (all vertices Z ≈ 0)
            min_z = face.vertices.map { |v| v.position.z }.min.abs
            next unless min_z <= GROUND_Z_TOLERANCE_IN
            if face.area > best_area
              best_area = face.area
              best = entity
            end
          end
        end

        return nil unless best

        auto_rename(model, best, 'Plot')
        Logger.info('auto_detect_plot', entity_id: best.persistent_id, area_sq_in: best_area.round(2))
        best
      end

      MIN_FLOOR_AREA_M2 = 6.0
      ELEVATION_TOLERANCE_M = 1.5

      # Discover floor-like groups by looking for top-level
      # groups/components (excluding the plot) that contain at
      # least one horizontal face.  Sort by bounding-box min-Z
      # and assign levels 0, 1, 2, …  Auto-renames each.
      def find_floors_fallback(model, plot_entity)
        plot_poly = polygon_from(plot_entity)
        plot_area = plot_poly ? plot_poly[:area_m2] : 0.0
        min_area = [MIN_FLOOR_AREA_M2, plot_area * 0.01].max

        candidates = top_level_groups(model).reject { |e| e == plot_entity }
        
        valid_candidates = []
        candidates.each do |entity|
          faces = inner_entities(entity).grep(Sketchup::Face)
          horiz = faces.select { |f| f.valid? && horizontal?(f) }
          
          if horiz.empty?
            Logger.info('floor_fallback_reject', entity: entity_name(entity), reason: 'no_horizontal_face')
            next
          end

          max_face_area = horiz.map { |f| Units.square_inches_to_square_meters(f.area) }.max
          if max_face_area < min_area
            Logger.info('floor_fallback_reject', entity: entity_name(entity), reason: 'area_below_threshold', area_m2: max_face_area.round(2))
            next
          end

          bb = entity.bounds
          bb_height = Units.inches_to_meters(bb.max.z - bb.min.z)
          if bb_height < 1.5
            Logger.warn('floor_fallback_reject', entity: entity_name(entity), reason: 'height_too_small', height_m: bb_height.round(3))
            next
          end

          valid_candidates << {
            entity: entity,
            area_m2: max_face_area,
            z_m: Units.inches_to_meters(bb.min.z),
            top_z_m: Units.inches_to_meters(bb.max.z)
          }
        end

        return [] if valid_candidates.empty?

        # Identify largest candidate for the 40% rule (logging only)
        largest_area = valid_candidates.map { |c| c[:area_m2] }.max
        threshold_40 = largest_area * 0.4
        valid_candidates.each do |c|
          if c[:area_m2] < threshold_40
            Logger.info('floor_fallback_small_area', entity: entity_name(c[:entity]), area_m2: c[:area_m2].round(2), threshold: threshold_40.round(2))
          end
        end

        # Elevation clustering
        valid_candidates.sort_by! { |c| c[:z_m] }
        clusters = []
        current_cluster = [valid_candidates.first]

        valid_candidates[1..-1].each do |c|
          if (c[:z_m] - current_cluster.first[:z_m]).abs <= ELEVATION_TOLERANCE_M
            current_cluster << c
          else
            clusters << current_cluster
            current_cluster = [c]
          end
        end
        clusters << current_cluster unless current_cluster.empty?

        # Select largest area candidate per cluster
        selected = clusters.map do |cluster|
          cluster.max_by { |c| c[:area_m2] }
        end

        # Building height and floor cap
        min_z_m = selected.first[:z_m]
        max_top_z_m = selected.map { |c| c[:top_z_m] }.max
        building_height_m = max_top_z_m - min_z_m
        
        max_reasonable = [(building_height_m / 2.4).ceil, 1].max

        # Sort selected candidates by Z
        selected.sort_by! { |c| c[:z_m] }

        if selected.length > max_reasonable
          rejected = selected[max_reasonable..-1]
          rejected.each do |c|
            Logger.info('floor_fallback_reject', entity: entity_name(c[:entity]), reason: 'exceeds_max_floor_count')
          end
          selected = selected.first(max_reasonable)
        end

        if selected.length > 0
          avg_height = building_height_m / selected.length
          if avg_height < 2.0
            Logger.warn(
              'floor_detection_suspicious',
              floors: selected.length,
              building_height_m: building_height_m.round(2),
              avg_floor_height_m: avg_height.round(2)
            )
          end
        end

        floors = []
        selected.each_with_index do |c, idx|
          entity = c[:entity]
          auto_rename(model, entity, "Floor #{idx}")
          Logger.info('floor_fallback_accept', level: idx, entity_id: entity.persistent_id, name: entity_name(entity), area_m2: c[:area_m2].round(2))
          floors << [idx, entity]
        end

        floors
      end

      # -- polygon extraction --------------------------------------------------

      def polygon_from(entity)
        return nil unless entity.valid?
        faces = inner_entities(entity).grep(Sketchup::Face)
        horiz = faces.select { |f| f.valid? && horizontal?(f) }
        return nil if horiz.empty?

        face = horiz.max_by(&:area)
        return nil unless face.valid?
        verts = face.outer_loop.vertices.map { |v| Units.point_to_xy_m(v.position) }
        {
          exterior: verts,
          area_m2: Units.square_inches_to_square_meters(face.area),
        }
      end

      def floor_payload(level, entity)
        return nil unless entity.valid?
        poly = polygon_from(entity)
        return nil unless poly

        height_m = slab_height(entity, level)
        height_m = 3.0 if height_m <= 0.0 # degenerate fallback

        is_habitable = attribute_or_default(entity, 'is_habitable', true)

        {
          level: level,
          polygon: { exterior: poly[:exterior] },
          height_m: height_m.round(3),
          is_habitable: is_habitable,
        }
      end

      # Compute floor height from horizontal face Z-spans.
      #
      # When a floor group contains 2+ horizontal faces (floor slab
      # and ceiling slab), measure the Z-distance between them using
      # the group's world-space transformation. This gives the true
      # slab-to-slab height.
      #
      # Falls back to bounding box height when only 0-1 horizontal
      # faces exist (e.g. a single slab plane).
      #
      # Diagnostic logging outputs all detected Z-elevations per
      # floor so the algorithm can be validated against real models.
      def slab_height(entity, level = nil)
        faces = inner_entities(entity).grep(Sketchup::Face)
        horiz = faces.select { |f| f.valid? && horizontal?(f) }

        if horiz.length >= 2
          # Collect world-space Z coordinates of horizontal face vertices.
          transform = entity.transformation
          z_values = []
          horiz.each do |face|
            face.vertices.each do |v|
              world_pt = transform * v.position
              z_values << world_pt.z
            end
          end

          # Unique Z-elevations (rounded to avoid float noise)
          unique_z = z_values.map { |z| Units.inches_to_meters(z).round(4) }.uniq.sort
          height_m = unique_z.last - unique_z.first

          Logger.info(
            'slab_height_detected',
            level: level,
            z_elevations_m: unique_z,
            slab_height_m: height_m.round(3),
            face_count: horiz.length,
            method: 'slab_span'
          )

          height_m
        else
          # Fallback: bounding box height
          bb = entity.bounds
          height_m = Units.inches_to_meters(bb.max.z - bb.min.z)

          Logger.info(
            'slab_height_detected',
            level: level,
            bbox_min_z_m: Units.inches_to_meters(bb.min.z).round(4),
            bbox_max_z_m: Units.inches_to_meters(bb.max.z).round(4),
            slab_height_m: height_m.round(3),
            face_count: horiz.length,
            method: 'bbox_fallback'
          )

          height_m
        end
      end

      # -- helpers -------------------------------------------------------------

      def entity_name(entity)
        case entity
        when Sketchup::Group then entity.name.to_s.strip
        when Sketchup::ComponentInstance
          (entity.name && !entity.name.strip.empty? ? entity.name : entity.definition.name).to_s.strip
        else ''
        end
      end

      def inner_entities(entity)
        if entity.is_a?(Sketchup::Group)
          entity.entities
        elsif entity.is_a?(Sketchup::ComponentInstance)
          entity.definition.entities
        else
          []
        end
      end

      def horizontal?(face)
        n = face.normal
        n.samedirection?(Z_AXIS) || n.samedirection?(Z_AXIS.reverse)
      end

      def attribute_or_default(entity, key, default)
        raw = entity.get_attribute('planara', key)
        return default if raw.nil?
        # SketchUp stores attribute values as their native type; accept
        # the obvious string forms too because dialogs round-trip JSON.
        return false if raw.to_s.downcase == 'false'
        return true if raw.to_s.downcase == 'true'
        raw
      end

      # All top-level groups and component instances in the model.
      def top_level_groups(model)
        model.entities.select do |e|
          e.is_a?(Sketchup::Group) || e.is_a?(Sketchup::ComponentInstance)
        end
      end

      # Rename an entity inside an undo-able operation.  If there's
      # already a model operation in progress (e.g. the live-validate
      # observer fired inside a transaction commit), we just set the
      # name directly — SketchUp batches it into the user's current
      # undo step.
      def auto_rename(model, entity, new_name)
        old_name = entity_name(entity)
        return if old_name == new_name

        # SketchUp raises if you start_operation inside another one.
        # The safest pattern: attempt start; if it raises, we're
        # already inside one — just set the name.
        # The 4th argument (transparent = true) prevents this
        # operation from firing observer callbacks, which avoids
        # the re-entrancy loop: auto_rename → commit → observer → validate → auto_rename.
        began = false
        begin
          model.start_operation('Planara auto-detect', true, false, true)
          began = true
        rescue StandardError
          # Already inside an operation — that's fine.
        end

        if entity.is_a?(Sketchup::Group)
          entity.name = new_name
        elsif entity.is_a?(Sketchup::ComponentInstance)
          entity.name = new_name
        end

        model.commit_operation if began
      rescue StandardError => e
        Logger.warn('auto_rename_failed', entity: old_name, new_name: new_name, error: e.message)
        model.abort_operation if began
      end
    end
  end
end
