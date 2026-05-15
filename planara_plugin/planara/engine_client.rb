# frozen_string_literal: true

require 'net/http'
require 'uri'
require 'json'
require 'securerandom'

require_relative 'config'
require_relative 'session'
require_relative 'logger'

module Planara
  # HTTP client for the planara_engine sidecar.
  #
  # Stdlib only (Net::HTTP) because SketchUp's Ruby is sandboxed
  # and has no gem manager. Connections are per-request: the engine
  # is on localhost so connection setup is microseconds, and
  # keeping a persistent connection across SketchUp's idle periods
  # is more pain than it's worth.
  module EngineClient
    # Raised when the engine returns a non-2xx, transport fails, or
    # we get JSON we can't parse. The plugin's UI layer should
    # catch this and show a friendly error.
    class EngineError < StandardError
      attr_reader :status, :code, :details

      def initialize(message, status: nil, code: nil, details: nil)
        super(message)
        @status = status
        @code = code
        @details = details
      end
    end

    module_function

    # Probe the engine. Cheap and dependency-free on the engine
    # side, so the supervisor can poll this in a tight loop while
    # the Python process is booting.
    #
    # @return [Hash] parsed /health body when up.
    # @raise [EngineError] when not.
    def health
      get('/health')
    end

    # POST /auth/login → { token: "..." } (wired up in Sprint 2).
    # @return [String] the JWT
    # @raise [EngineError]
    def login(username:, password:)
      body = post('/auth/login', { username: username, password: password }, authenticated: false)
      Session.token = body.fetch('token')
      Session.token
    end

    # POST /validate with a snapshot, return the violations envelope.
    # Snapshot extraction lives in geometry/extractor.rb (Sprint 2).
    def validate(snapshot)
      post('/validate', snapshot, authenticated: true)
    end

    # -- transport ----------------------------------------------------------

    def get(path)
      request(Net::HTTP::Get.new(uri_for(path).request_uri), uri_for(path))
    end

    def post(path, payload, authenticated: true)
      uri = uri_for(path)
      req = Net::HTTP::Post.new(uri.request_uri)
      req['Content-Type'] = 'application/json'
      req.body = JSON.generate(payload)
      apply_auth(req) if authenticated
      request(req, uri)
    end

    def uri_for(path)
      URI.join(Config.engine_url, path)
    end

    def apply_auth(req)
      Session.auth_headers.each { |k, v| req[k] = v }
    end

    def request(req, uri)
      req['X-Request-ID'] ||= SecureRandom.hex(16)
      req['Accept'] = 'application/json'

      Logger.debug('engine_request', method: req.method, path: uri.request_uri, request_id: req['X-Request-ID'])

      response = open_http(uri).request(req)
      parse_response(response, req['X-Request-ID'])
    rescue EngineError
      raise
    rescue StandardError => e
      raise EngineError, "engine transport error: #{e.class}: #{e.message}"
    end

    def open_http(uri)
      http = Net::HTTP.new(uri.host, uri.port)
      http.open_timeout = Config.request_timeout_s
      http.read_timeout = Config.request_timeout_s
      http.use_ssl = (uri.scheme == 'https')
      http
    end

    def parse_response(response, request_id)
      body = response.body.to_s
      parsed = body.empty? ? {} : JSON.parse(body)

      status = response.code.to_i
      if status.between?(200, 299)
        Logger.debug('engine_response', status: status, request_id: request_id)
        return parsed
      end

      err = parsed['error'] || {}
      Logger.warn(
        'engine_error',
        status: status,
        code: err['code'],
        message: err['message'],
        request_id: request_id
      )
      raise EngineError.new(
        err['message'] || "engine returned HTTP #{status}",
        status: status,
        code: err['code'],
        details: err['details']
      )
    rescue JSON::ParserError => e
      raise EngineError, "engine returned non-JSON body (HTTP #{response.code}): #{e.message}"
    end
  end
end
