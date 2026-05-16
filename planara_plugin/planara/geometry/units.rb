# frozen_string_literal: true

module Planara
  module Geometry
    # Unit conversion helpers.
    #
    # SketchUp stores lengths internally in inches regardless of the
    # model's display unit. Everything we send across the wire to
    # the Python engine is in METERS — the engine does no unit
    # conversion. This module owns the conversion so the rest of
    # the extractor stays unit-agnostic.
    module Units
      INCH_TO_METER = 0.0254
      METER_TO_INCH = 1.0 / INCH_TO_METER

      module_function

      # Convert a SketchUp length value (inches) to meters.
      def inches_to_meters(value_inches)
        value_inches.to_f * INCH_TO_METER
      end

      # Convert a SketchUp Geom::Point3d (inches) to a 2-element
      # [x_m, y_m] array, dropping z. Used for plot/footprint
      # polygons which are planar in the XY plane.
      def point_to_xy_m(point)
        [inches_to_meters(point.x), inches_to_meters(point.y)]
      end

      # Convert a SketchUp area in square inches to square meters.
      def square_inches_to_square_meters(area_sq_in)
        area_sq_in.to_f * INCH_TO_METER * INCH_TO_METER
      end
    end
  end
end
