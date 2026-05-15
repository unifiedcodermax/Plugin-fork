# frozen_string_literal: true

module Planara
  # Plugin-side configuration.
  #
  # Mirrors the subset of planara_engine settings that the plugin
  # needs to know about. Resolved from environment variables when
  # SketchUp launches; falls back to sensible local-dev defaults.
  #
  # Everything is read once at boot. Treat the returned object as
  # immutable — there is no `set`.
  module Config
    DEFAULT_HOST = '127.0.0.1'
    DEFAULT_PORT = 8765
    DEFAULT_HEALTH_TIMEOUT_S = 15.0
    DEFAULT_REQUEST_TIMEOUT_S = 5.0

    module_function

    # @return [String] base URL for the engine, e.g. "http://127.0.0.1:8765"
    def engine_url
      ENV.fetch('PLANARA_ENGINE_URL') do
        "http://#{ENV.fetch('PLANARA_HOST', DEFAULT_HOST)}:" \
          "#{ENV.fetch('PLANARA_PORT', DEFAULT_PORT)}"
      end
    end

    # @return [String, nil] explicit path/command for the engine binary.
    #   nil means "look on PATH for `planara-engine`".
    def engine_cmd
      ENV['PLANARA_ENGINE_CMD']
    end

    # @return [Float] seconds to wait for the engine's /health to respond
    #   after spawning the sidecar before giving up.
    def health_timeout_s
      ENV.fetch('PLANARA_HEALTH_TIMEOUT_S', DEFAULT_HEALTH_TIMEOUT_S).to_f
    end

    # @return [Float] per-request HTTP timeout for engine_client calls.
    def request_timeout_s
      ENV.fetch('PLANARA_REQUEST_TIMEOUT_S', DEFAULT_REQUEST_TIMEOUT_S).to_f
    end

    # @return [String] absolute path to the planara_plugin/planara directory.
    def plugin_root
      File.expand_path(__dir__)
    end

    # @return [String] human-friendly summary, useful in logs and UI.
    def summary
      "Planara plugin → #{engine_url} (timeout: #{request_timeout_s}s)"
    end
  end
end
