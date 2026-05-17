# frozen_string_literal: true

# Runs outside SketchUp: `ruby planara_plugin/test/test_engine_client.rb`.
#
# We stub EngineClient.open_http to hand back a fake transport that
# returns a canned Net::HTTPResponse. This exercises the URL shape,
# headers, body serialization, and response parsing — the parts of
# the client that are easy to break and have no SketchUp dependency.
# A real Net::HTTP roundtrip is out of scope here; that's covered by
# the engine's integration tests on the Python side.

require 'json'
require 'minitest/autorun'
require 'net/http'

require_relative '../planara/engine_client'
require_relative '../planara/session'

module Planara
  # Minimal fake transport: capture the outbound Net::HTTP::Request,
  # return a Net::HTTPResponse built from a small spec.
  class FakeHttp
    attr_reader :captured

    def initialize(status:, body:, content_type: 'application/json')
      @status = status
      @body = body
      @content_type = content_type
    end

    def request(req)
      @captured = req

      klass = Net::HTTPResponse::CODE_TO_OBJ.fetch(@status.to_s) do
        # Fallback for codes Net::HTTP doesn't ship a class for.
        Net::HTTPResponse
      end
      response = klass.new('1.1', @status.to_s, 'X')
      response.instance_variable_set(:@body, @body)
      response.instance_variable_set(:@read, true)
      response['Content-Type'] = @content_type
      response
    end
  end

  class TestEngineClientHistory < Minitest::Test
    def setup
      Session.token = 'test-token'
      @captured_uri = nil
    end

    def teardown
      Session.clear
    end

    # Install a fake transport for one request. `fake` is the
    # FakeHttp instance; we also record the URI passed to open_http
    # on the test instance so assertions can read it after the
    # with_fake block returns.
    def with_fake(fake)
      original = EngineClient.method(:open_http)
      test_self = self
      EngineClient.define_singleton_method(:open_http) do |uri|
        test_self.instance_variable_set(:@captured_uri, uri)
        fake
      end
      yield
    ensure
      EngineClient.singleton_class.send(:remove_method, :open_http)
      EngineClient.define_singleton_method(:open_http, original)
    end

    def captured_uri
      @captured_uri
    end

    # -- save_history ----------------------------------------------------

    def test_save_history_posts_snapshot_json
      archive = { 'report_id' => 'abc', 'response' => { 'ok' => true } }
      fake = FakeHttp.new(status: 201, body: JSON.generate(archive))

      with_fake(fake) do
        result = EngineClient.save_history({ snapshot_id: 'u' })
        assert_equal(archive, result)
      end

      req = fake.captured
      assert_equal('POST', req.method)
      assert_equal('/history', captured_uri.path)
      assert_equal('application/json', req['Content-Type'])
      assert_equal('Bearer test-token', req['Authorization'])
      assert_equal({ 'snapshot_id' => 'u' }, JSON.parse(req.body))
    end

    # -- list_history ----------------------------------------------------

    def test_list_history_with_defaults_only_sends_limit_offset
      fake = FakeHttp.new(status: 200, body: JSON.generate({ 'items' => [], 'total' => 0 }))

      with_fake(fake) do
        EngineClient.list_history
      end

      # nil filters are dropped; limit/offset retain their defaults.
      query = captured_uri.query
      assert_match(/limit=20/, query)
      assert_match(/offset=0/, query)
      refute_match(/city=/, query)
      refute_match(/zone=/, query)
    end

    def test_list_history_serializes_filters
      fake = FakeHttp.new(status: 200, body: JSON.generate({ 'items' => [], 'total' => 0 }))

      with_fake(fake) do
        EngineClient.list_history(limit: 5, offset: 10, city: 'Bangalore', classification: 'CBD', zone: 'Residential', ok: false)
      end

      query = captured_uri.query
      assert_match(/limit=5/, query)
      assert_match(/offset=10/, query)
      assert_match(/city=Bangalore/, query)
      assert_match(/classification=CBD/, query)
      assert_match(/zone=Residential/, query)
      assert_match(/ok=false/, query)
    end

    def test_list_history_url_encodes_special_chars
      fake = FakeHttp.new(status: 200, body: JSON.generate({ 'items' => [], 'total' => 0 }))

      with_fake(fake) do
        EngineClient.list_history(city: 'San Jose')
      end

      # Whitespace must be percent-encoded (+ or %20) — either is
      # legal in a query but the engine relies on standard parsing,
      # so any encoded form is acceptable; the raw space is not.
      query = captured_uri.query
      refute_match(/city=San Jose/, query)
      assert(query.include?('city=San+Jose') || query.include?('city=San%20Jose'),
             "expected encoded space in #{query.inspect}")
    end

    # -- get_history -----------------------------------------------------

    def test_get_history_hits_per_id_path
      payload = { 'report_id' => 'r1', 'snapshot' => {}, 'response' => { 'ok' => true } }
      fake = FakeHttp.new(status: 200, body: JSON.generate(payload))

      with_fake(fake) do
        assert_equal(payload, EngineClient.get_history('r1'))
      end

      assert_equal('/history/r1', captured_uri.path)
      assert_equal('GET', fake.captured.method)
      assert_equal('Bearer test-token', fake.captured['Authorization'])
    end

    # -- get_history_html ------------------------------------------------

    def test_get_history_html_returns_raw_body_string
      html = '<!doctype html><title>x</title>'
      fake = FakeHttp.new(status: 200, body: html, content_type: 'text/html; charset=utf-8')

      with_fake(fake) do
        out = EngineClient.get_history_html('r1')
        assert_equal(html, out)
      end

      assert_equal('/history/r1/html', captured_uri.path)
      assert_equal('text/html', fake.captured['Accept'])
    end

    def test_get_history_html_translates_engine_error
      err_body = JSON.generate({ 'error' => { 'code' => 'not_found', 'message' => 'gone' } })
      fake = FakeHttp.new(status: 404, body: err_body)

      with_fake(fake) do
        err = assert_raises(EngineClient::EngineError) { EngineClient.get_history_html('r1') }
        assert_equal(404, err.status)
        assert_equal('not_found', err.code)
        assert_equal('gone', err.message)
      end
    end

    # -- auto_diff -------------------------------------------------------

    def test_auto_diff_path
      fake = FakeHttp.new(status: 200, body: JSON.generate({ 'verdict' => 'unchanged' }))

      with_fake(fake) do
        assert_equal({ 'verdict' => 'unchanged' }, EngineClient.auto_diff('r1'))
      end

      assert_equal('/history/r1/diff', captured_uri.path)
    end

    def test_auto_diff_html_returns_html_body
      html = '<!doctype html><body>diff</body>'
      fake = FakeHttp.new(status: 200, body: html, content_type: 'text/html')

      with_fake(fake) do
        assert_equal(html, EngineClient.auto_diff_html('r1'))
      end

      assert_equal('/history/r1/diff/html', captured_uri.path)
    end

    # -- explicit_diff ---------------------------------------------------

    def test_explicit_diff_passes_from_and_to_as_query
      fake = FakeHttp.new(status: 200, body: JSON.generate({ 'verdict' => 'regressed' }))

      with_fake(fake) do
        EngineClient.explicit_diff('aaa', 'bbb')
      end

      assert_equal('/history/diff', captured_uri.path)
      query = captured_uri.query
      assert_match(/from=aaa/, query)
      assert_match(/to=bbb/, query)
    end

    def test_explicit_diff_html_returns_html_body
      html = '<!doctype html><body>pair</body>'
      fake = FakeHttp.new(status: 200, body: html, content_type: 'text/html')

      with_fake(fake) do
        assert_equal(html, EngineClient.explicit_diff_html('aaa', 'bbb'))
      end

      assert_equal('/history/diff/html', captured_uri.path)
      assert_match(/from=aaa.*to=bbb|to=bbb.*from=aaa/, captured_uri.query)
    end

    # -- error envelope --------------------------------------------------

    def test_json_endpoint_translates_error_envelope
      body = JSON.generate({ 'error' => { 'code' => 'authentication_failed', 'message' => 'bad token' } })
      fake = FakeHttp.new(status: 401, body: body)

      with_fake(fake) do
        err = assert_raises(EngineClient::EngineError) { EngineClient.list_history }
        assert_equal(401, err.status)
        assert_equal('authentication_failed', err.code)
        assert_equal('bad token', err.message)
      end
    end

    def test_raw_endpoint_tolerates_non_json_error_body
      # Some upstream layers (eg a reverse proxy) might return a
      # text/html 502 with no JSON envelope at all. The client
      # should still surface a useful EngineError instead of
      # blowing up with JSON::ParserError.
      fake = FakeHttp.new(status: 502, body: '<html>bad gateway</html>', content_type: 'text/html')

      with_fake(fake) do
        err = assert_raises(EngineClient::EngineError) { EngineClient.get_history_html('r1') }
        assert_equal(502, err.status)
      end
    end
  end
end
