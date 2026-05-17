# frozen_string_literal: true

module Planara
  # Holds plugin-side session state: the JWT, plus the project
  # metadata the user enters once and the live-validate loop reuses
  # on every model commit (no re-prompting per edit).
  #
  # Single module-level instance is fine: SketchUp is a single-user
  # desktop app. A class-with-instance would be overkill.
  module Session
    module_function

    def token
      @token
    end

    def token=(value)
      @token = value
    end

    def clear
      @token = nil
      @project = nil
      @last_report_id = nil
    end

    def authenticated?
      !@token.nil? && !@token.empty?
    end

    # @return [Hash{String => String}] headers to attach to engine requests.
    def auth_headers
      authenticated? ? { 'Authorization' => "Bearer #{@token}" } : {}
    end

    # Canonical project metadata for the current SketchUp model:
    # { city:, classification:, zone:, overlays:, parking_slots: }.
    # nil until the user completes the project-setup prompt.
    def project
      @project
    end

    def project=(value)
      @project = value
    end

    def project_ready?
      p = @project
      !p.nil? && !p[:city].to_s.empty? &&
        !p[:classification].to_s.empty? && !p[:zone].to_s.empty?
    end

    # Most-recently-saved report_id for the current SketchUp
    # session. Powers "Open last report in browser" — only valid
    # for this process; we deliberately don't persist it across
    # restarts so we never point at a stale row after a wipe.
    def last_report_id
      @last_report_id
    end

    def last_report_id=(value)
      @last_report_id = value
    end
  end
end
