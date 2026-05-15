# frozen_string_literal: true

module Planara
  # Holds plugin-side session state — currently just the JWT token
  # returned by the engine's /auth/login (added in Sprint 2).
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
    end

    def authenticated?
      !@token.nil? && !@token.empty?
    end

    # @return [Hash{String => String}] headers to attach to engine requests.
    def auth_headers
      authenticated? ? { 'Authorization' => "Bearer #{@token}" } : {}
    end
  end
end
