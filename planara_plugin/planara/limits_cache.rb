# frozen_string_literal: true

module Planara
  # Caches compliance limits from the last engine validation response.
  #
  # Each limit stores its value alongside provenance (source rule_id
  # and a human-readable label) so the in-design observer can tell
  # the user *why* a limit exists:
  #
  #   {
  #     value:  45.0,
  #     source: "blr.overlay.airport.height",
  #     label:  "Airport Height Restriction"
  #   }
  #
  # Populated by Boot.show_validation_result after every engine
  # response. The in-design observer reads from here — it never
  # invents or assumes limits.
  module LimitsCache
    module_function

    # -- readers ---------------------------------------------------------------

    # @return [Hash, nil] { value:, source:, label: } or nil when no
    #   height limit is active.
    def max_height
      @max_height
    end

    # @return [Float, nil] the numeric limit, or nil.
    def max_height_m
      @max_height&.dig(:value)
    end

    # @return [Hash, nil]
    def max_fsi
      @max_fsi
    end

    # @return [Hash, nil]
    def min_room_height
      @min_room_height
    end

    def min_room_height_m
      @min_room_height&.dig(:value)
    end

    # @return [Hash, nil]
    def max_coverage
      @max_coverage
    end

    def max_coverage_pct
      @max_coverage&.dig(:value)
    end

    # -- population from engine response ---------------------------------------

    # Populate the cache from a ValidationResponse hash.
    #
    # The engine merges every evaluator's ``computed`` dict into the
    # top-level ``metrics`` — so keys like ``max_fsi``,
    # ``max_height_m``, ``max_coverage_pct``, ``min_height_m`` appear
    # there when the corresponding rule fired. Violations carry the
    # rule_id and category which we mine for provenance labels.
    #
    # @param response [Hash] the raw engine response
    def populate(response)
      metrics    = response['metrics'] || response[:metrics] || {}
      violations = response['violations'] || response[:violations] || []

      # -- Height --
      @max_height = extract_limit(
        metrics, violations,
        metric_key: 'max_height_m',
        category: 'height',
        fallback_label: 'Building Height Limit'
      )

      # -- FSI --
      @max_fsi = extract_limit(
        metrics, violations,
        metric_key: 'max_fsi',
        category: 'fsi',
        fallback_label: 'FSI / FAR Limit'
      )

      # -- Room height --
      @min_room_height = extract_limit(
        metrics, violations,
        metric_key: 'min_height_m',
        category: 'room_height',
        fallback_label: 'Minimum Room Height'
      )

      # -- Coverage --
      @max_coverage = extract_limit(
        metrics, violations,
        metric_key: 'max_coverage_pct',
        category: 'coverage',
        fallback_label: 'Ground Coverage Limit'
      )

      Logger.info(
        'limits_cache_populated',
        max_height_m: max_height_m,
        min_room_height_m: min_room_height_m,
        max_coverage_pct: max_coverage_pct
      )
    end

    def clear
      @max_height = nil
      @max_fsi = nil
      @min_room_height = nil
      @max_coverage = nil
    end

    # -- internal helpers ------------------------------------------------------
    private

    def self.extract_limit(metrics, violations, metric_key:, category:, fallback_label:)
      value = metrics[metric_key]
      return nil if value.nil?

      # Find the first violation/rule in this category for provenance.
      matching = violations.find { |v| (v['category'] || v[:category]) == category }
      source = matching ? (matching['rule_id'] || matching[:rule_id]) : nil

      # Derive a human label from the rule_id:
      #   "blr.overlay.airport.height" → "Airport Height"
      label = if source
                parts = source.to_s.split('.')
                # Drop city prefix and category suffix, titleize the middle
                middle = parts[1..-1] || []
                middle.map { |p| p.gsub('_', ' ').capitalize }.join(' ')
              else
                fallback_label
              end

      { value: value.to_f, source: source, label: label }
    end
  end
end
