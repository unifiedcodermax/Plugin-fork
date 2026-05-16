# frozen_string_literal: true

require 'securerandom'

require_relative 'units'
require_relative '../logger'

module Planara
  module Geometry
    # Extracts a Snapshot payload from the active SketchUp model.
    #
    # Discovery rules (deliberately conservative for the MVP):
    #
    #   PLOT
    #     - Looks for a Sketchup::Group OR Sketchup::ComponentInstance
    #       at the top level whose ``name`` matches /^plot$/i.
    #     - Inside it, picks the single horizontal Sketchup::Face
    #       (normal parallel to Z) with the LARGEST area as the
    #       plot polygon.
    #     - Z-coordinates are dropped; we treat the plot as 2D.
    #
    #   FLOORS
    #     - Top-level groups/components named "Floor N" (case-insensitive,
    #       any whitespace). Numeric N becomes Floor.level.
    #     - The largest horizontal face inside becomes Floor.polygon.
    #     - height_m comes from the Z-extent of the group's bounding
    #       box. Default 3.0 m when degenerate.
    #     - is_habitable defaults to true. If the group/component has
    #       an attribute ``planara/is_habitable`` set to "false" we
    #       honor it — lets users mark stilts/services without
    #       rebuilding the extractor.
    #
    # When discovery fails (no plot or no floors), the extractor
    # raises ExtractionError with a message the plugin UI surfaces.
    # Future sprints will add fallbacks (selection-based plot input,
    # face-based floor inference) — this strict version is the
    # foundation that ships in the MVP demo.
    module Extractor
      class ExtractionError < StandardError; end

      FLOOR_NAME_REGEX = /^floor\s*(-?\d+)$/i.freeze
      PLOT_NAME_REGEX  = /^plot$/i.freeze

      module_function

      # Build a Snapshot payload from the active model.
      #
      # @param model [Sketchup::Model]
      # @param project [Hash] { city:, classification:, zone: } pulled
      #   from the project-setup dialog.
      # @return [Hash] the JSON-ready Snapshot payload.
      def extract(model:, project:)
        raise ExtractionError, 'no active model' unless model

        plot = find_plot(model)
        floors = find_floors(model)
        raise ExtractionError, 'no plot group/component named "Plot" found' unless plot
        raise ExtractionError, 'no floors found (expected groups named "Floor 0", "Floor 1", ...)' if floors.empty?

        plot_polygon = polygon_from(plot)
        raise ExtractionError, 'plot has no horizontal face' unless plot_polygon

        floor_payloads = floors.map { |level, entity| floor_payload(level, entity) }.compact

        {
          snapshot_id: SecureRandom.uuid,
          project: project,
          plot: {
            polygon: { exterior: plot_polygon[:exterior] },
            area_m2: plot_polygon[:area_m2],
          },
          building: { floors: floor_payloads },
        }
      end

      # -- discovery -----------------------------------------------------------

      def find_plot(model)
        model.entities.find do |e|
          (e.is_a?(Sketchup::Group) || e.is_a?(Sketchup::ComponentInstance)) &&
            entity_name(e) =~ PLOT_NAME_REGEX
        end
      end

      def find_floors(model)
        out = []
        model.entities.each do |e|
          next unless e.is_a?(Sketchup::Group) || e.is_a?(Sketchup::ComponentInstance)
          name = entity_name(e)
          if (match = FLOOR_NAME_REGEX.match(name))
            out << [match[1].to_i, e]
          end
        end
        out.sort_by!(&:first)
        out
      end

      # -- polygon extraction --------------------------------------------------

      def polygon_from(entity)
        faces = inner_entities(entity).grep(Sketchup::Face)
        horiz = faces.select { |f| horizontal?(f) }
        return nil if horiz.empty?

        face = horiz.max_by(&:area)
        verts = face.outer_loop.vertices.map { |v| Units.point_to_xy_m(v.position) }
        {
          exterior: verts,
          area_m2: Units.square_inches_to_square_meters(face.area),
        }
      end

      def floor_payload(level, entity)
        poly = polygon_from(entity)
        return nil unless poly

        bb = entity.bounds
        height_m = Units.inches_to_meters(bb.max.z - bb.min.z)
        height_m = 3.0 if height_m <= 0.0 # degenerate fallback

        is_habitable = attribute_or_default(entity, 'is_habitable', true)

        {
          level: level,
          polygon: { exterior: poly[:exterior] },
          height_m: height_m.round(3),
          is_habitable: is_habitable,
        }
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
    end
  end
end
