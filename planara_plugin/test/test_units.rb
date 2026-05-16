# frozen_string_literal: true

# Runs outside SketchUp: `ruby planara_plugin/test/test_units.rb`.
#
# The Extractor itself depends on Sketchup::* types and cannot be
# meaningfully unit-tested outside the host app. Units is pure
# arithmetic — pinning it here catches a future "let me just tweak
# the conversion factor" mistake.

require 'minitest/autorun'

require_relative '../planara/geometry/units'

class TestUnits < Minitest::Test
  include Planara::Geometry

  def test_inches_to_meters
    assert_in_delta(0.0254, Units.inches_to_meters(1), 1e-9)
    assert_in_delta(2.54, Units.inches_to_meters(100), 1e-9)
    assert_equal(0.0, Units.inches_to_meters(0))
  end

  def test_square_inches_to_square_meters
    # 1 in^2 = 0.00064516 m^2
    assert_in_delta(0.00064516, Units.square_inches_to_square_meters(1), 1e-12)
    # 144 in^2 = 1 ft^2 = 0.09290304 m^2
    assert_in_delta(0.09290304, Units.square_inches_to_square_meters(144), 1e-9)
  end

  def test_point_to_xy_m
    point = Struct.new(:x, :y, :z).new(100, 200, 50)
    xy = Units.point_to_xy_m(point)
    assert_equal(2, xy.length)
    assert_in_delta(2.54, xy[0], 1e-9)
    assert_in_delta(5.08, xy[1], 1e-9)
  end
end
