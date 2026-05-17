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
      get('/health', authenticated: false)
    end

    # Fetch the currently authenticated user from the engine.
    # @raise [EngineError] when no/expired token, or any transport error.
    def me
      get('/auth/me')
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

    # -- /history ----------------------------------------------------------

    # POST /history — evaluate snapshot, persist, return the
    # ArchivalReport JSON (includes report_id).
    def save_history(snapshot)
      post('/history', snapshot)
    end

    # GET /history — paginated list of the calling user's reports.
    # All filter args are optional; nil values are dropped from the
    # query string so the engine applies its defaults.
    def list_history(limit: 20, offset: 0, city: nil, classification: nil, zone: nil, ok: nil)
      params = { limit: limit, offset: offset, city: city, classification: classification, zone: zone, ok: ok }
      get(with_query('/history', params))
    end

    # GET /history/{id} — fetch one stored archive as JSON.
    def get_history(report_id)
      get("/history/#{url_segment(report_id)}")
    end

    # GET /history/{id}/html — pre-rendered HTML for the archive.
    # Returns the raw HTML body as a string (not JSON-parsed).
    def get_history_html(report_id)
      get_raw("/history/#{url_segment(report_id)}/html")
    end

    # GET /history/{id}/diff — auto-diff this report against the
    # most-recent prior with the same (city, classification, zone).
    def auto_diff(report_id)
      get("/history/#{url_segment(report_id)}/diff")
    end

    # GET /history/{id}/diff/html — HTML variant of auto_diff.
    def auto_diff_html(report_id)
      get_raw("/history/#{url_segment(report_id)}/diff/html")
    end

    # GET /history/diff?from=...&to=... — explicit pairwise diff.
    def explicit_diff(from_id, to_id)
      get(with_query('/history/diff', from: from_id, to: to_id))
    end

    # GET /history/diff/html?from=...&to=... — HTML variant.
    def explicit_diff_html(from_id, to_id)
      get_raw(with_query('/history/diff/html', from: from_id, to: to_id))
    end

    # -- transport ----------------------------------------------------------

    def get(path, authenticated: true)
      uri = uri_for(path)
      req = Net::HTTP::Get.new(uri.request_uri)
      apply_auth(req) if authenticated
      request(req, uri)
    end

    # GET that returns the response body as a raw String (no JSON
    # parsing). Used for the /history/.../html endpoints. Errors
    # still come back as JSON envelopes from the engine, so we try
    # to parse the body on non-2xx to surface a useful EngineError.
    def get_raw(path, authenticated: true)
      uri = uri_for(path)
      req = Net::HTTP::Get.new(uri.request_uri)
      req['Accept'] = 'text/html'
      apply_auth(req) if authenticated
      request_raw(req, uri)
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

    # Build "path?k=v&k2=v2" from a hash, dropping nil values so the
    # engine sees an absent param rather than the literal string
    # "None"/"nil". Booleans serialize as "true"/"false" — FastAPI's
    # Query parser accepts that.
    def with_query(path, params)
      pairs = params.compact.map do |k, v|
        "#{URI.encode_www_form_component(k.to_s)}=#{URI.encode_www_form_component(v.to_s)}"
      end
      pairs.empty? ? path : "#{path}?#{pairs.join('&')}"
    end

    # Encode a path segment (UUID strings are already safe; this is
    # defensive against future identifiers that might contain
    # reserved characters).
    def url_segment(value)
      URI.encode_www_form_component(value.to_s)
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

    # Same plumbing as ``request``, but returns the response body
    # verbatim on 2xx instead of JSON-parsing it. Non-2xx still goes
    # through the JSON error envelope path — the engine emits HTML
    # only on success.
    def request_raw(req, uri)
      req['X-Request-ID'] ||= SecureRandom.hex(16)

      Logger.debug('engine_request', method: req.method, path: uri.request_uri, request_id: req['X-Request-ID'])

      response = open_http(uri).request(req)
      status = response.code.to_i
      if status.between?(200, 299)
        Logger.debug('engine_response', status: status, request_id: req['X-Request-ID'])
        return response.body.to_s
      end

      raise_for_error(response, req['X-Request-ID'])
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

      raise_engine_error(status, parsed, request_id)
    rescue JSON::ParserError => e
      raise EngineError, "engine returned non-JSON body (HTTP #{response.code}): #{e.message}"
    end

    # Parse a non-2xx response as a JSON error envelope and raise.
    # Used by request_raw, where success bodies are HTML but error
    # bodies are still the standard JSON shape.
    def raise_for_error(response, request_id)
      body = response.body.to_s
      parsed =
        begin
          body.empty? ? {} : JSON.parse(body)
        rescue JSON::ParserError
          {}
        end
      raise_engine_error(response.code.to_i, parsed, request_id)
    end

    def raise_engine_error(status, parsed, request_id)
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
    end
  end
end
