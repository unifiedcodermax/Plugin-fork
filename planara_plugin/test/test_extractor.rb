# frozen_string_literal: true

# Runs outside SketchUp: `ruby planara_plugin/test/test_extractor.rb`.
#
# These tests exercise the pure-data helpers on Extractor —
# build_payload and normalize_project — which take plain hashes
# and don't touch Sketchup::*. They pin the Ruby↔Python wire format:
# any change here that breaks them is a contract break.

require 'json'
require 'minitest/autorun'

require_relative '../planara/geometry/extractor'

module Planara
  module Geometry
    class TestBuildPayload < Minitest::Test
      def setup
        @plot = {
          exterior: [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
          area_m2: 100.0,
        }
        @floors = [
          { level: 0, polygon: { exterior: [[1, 1], [5, 1], [5, 5], [1, 5]] }, height_m: 3.0, is_habitable: true },
          { level: 1, polygon: { exterior: [[1, 1], [5, 1], [5, 5], [1, 5]] }, height_m: 3.0, is_habitable: true },
        ]
      end

      def build(project: { city: 'Bangalore', classification: 'CBD', zone: 'Residential' }, parking: 0)
        Extractor.build_payload(
          plot_polygon: @plot,
          floor_payloads: @floors,
          project: project,
          parking_slots: parking
        )
      end

      def test_schema_version_is_pinned
        # The plugin's declared wire-format version. The engine treats
        # mismatches as warnings; we still pin the value so an
        # accidental bump is intentional.
        assert_equal('1.0', build[:schema_version])
        assert_equal('1.0', Extractor::SCHEMA_VERSION)
      end

      def test_snapshot_id_is_uuid_shape
        payload = build
        # Plain string, 8-4-4-4-12 hex digits.
        assert_match(/\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\z/, payload[:snapshot_id])
      end

      def test_project_round_trip_with_symbol_keys
        payload = build(project: { city: 'Bangalore', classification: 'CBD', zone: 'Commercial', overlays: ['airport'] })
        assert_equal('Bangalore', payload[:project][:city])
        assert_equal('CBD', payload[:project][:classification])
        assert_equal('Commercial', payload[:project][:zone])
        assert_equal(['airport'], payload[:project][:overlays])
      end

      def test_project_round_trip_with_string_keys
        # Dialog round-trips JSON, which gives us string keys. The
        # normalizer must accept both — the rest of the plugin
        # should not have to care which form arrived.
        payload = build(project: { 'city' => 'Mumbai', 'classification' => 'CBD', 'zone' => 'Residential', 'overlays' => ['heritage_influence'] })
        assert_equal('Mumbai', payload[:project][:city])
        assert_equal(['heritage_influence'], payload[:project][:overlays])
      end

      def test_overlays_default_to_empty
        payload = build(project: { city: 'Bangalore', classification: 'CBD', zone: 'Residential' })
        assert_equal([], payload[:project][:overlays])
      end

      def test_overlays_strip_and_drop_empties
        # The setup dialog hands us a free-text comma-split — verify
        # we don't propagate stray whitespace or empty strings (the
        # engine matches overlays exactly, so " airport" would
        # silently never fire).
        payload = build(project: { city: 'Bangalore', classification: 'CBD', zone: 'Residential', overlays: ['  airport ', '', 'heritage_influence', '   '] })
        assert_equal(['airport', 'heritage_influence'], payload[:project][:overlays])
      end

      def test_plot_carries_through
        payload = build
        assert_equal(@plot[:exterior], payload[:plot][:polygon][:exterior])
        assert_in_delta(100.0, payload[:plot][:area_m2], 1e-9)
      end

      def test_building_carries_floors_and_parking
        payload = build(parking: 7)
        assert_equal(2, payload[:building][:floors].length)
        assert_equal(7, payload[:building][:parking_slots_provided])
      end

      def test_parking_coerced_to_integer
        payload = build(parking: '12')
        assert_equal(12, payload[:building][:parking_slots_provided])
      end

      def test_json_round_trip
        # The payload must JSON-serialize cleanly — that's how it
        # leaves the plugin. A non-trivial change (e.g. introducing
        # a Symbol value somewhere it gets stringified asymmetrically)
        # would be caught here.
        payload = build(project: { city: 'Bangalore', classification: 'CBD', zone: 'Residential', overlays: ['airport'] }, parking: 3)
        json = JSON.generate(payload)
        parsed = JSON.parse(json)

        assert_equal('1.0', parsed['schema_version'])
        assert_equal('Bangalore', parsed['project']['city'])
        assert_equal(['airport'], parsed['project']['overlays'])
        assert_equal(3, parsed['building']['parking_slots_provided'])
        assert_equal(2, parsed['building']['floors'].length)
      end
    end

    class TestNormalizeProject < Minitest::Test
      def test_nil_project_yields_empty_strings_and_overlays
        out = Extractor.normalize_project(nil)
        assert_equal('', out[:city])
        assert_equal('', out[:classification])
        assert_equal('', out[:zone])
        assert_equal([], out[:overlays])
      end

      def test_overlays_coerced_to_strings
        # Defensive: a symbol overlay from older Ruby code paths must
        # still ship as a string so the engine's exact-match filter
        # works.
        out = Extractor.normalize_project(overlays: [:airport, :heritage_influence])
        assert_equal(['airport', 'heritage_influence'], out[:overlays])
      end
    end
  end
end
