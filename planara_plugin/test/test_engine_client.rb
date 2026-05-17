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

    # -- /projects -------------------------------------------------------
    #
    # The plugin's project picker leans on these three endpoints —
    # any URL / verb / body drift here breaks the picker silently.
    # The tests stub the transport so we can assert path + payload
    # without booting the engine.

    def test_create_project_posts_payload_and_returns_row
      row = { 'id' => 42, 'name' => '5th Main', 'city' => 'Bangalore',
              'classification' => 'CBD', 'zone' => 'Residential',
              'created_at' => '2026-05-17T00:00:00Z' }
      fake = FakeHttp.new(status: 201, body: JSON.generate(row))

      with_fake(fake) do
        result = EngineClient.create_project(
          name: '5th Main',
          city: 'Bangalore',
          classification: 'CBD',
          zone: 'Residential',
        )
        assert_equal(row, result)
      end

      req = fake.captured
      assert_equal('POST', req.method)
      assert_equal('/projects', captured_uri.path)
      assert_equal('application/json', req['Content-Type'])
      assert_equal('Bearer test-token', req['Authorization'])
      body = JSON.parse(req.body)
      assert_equal('5th Main', body['name'])
      assert_equal('Bangalore', body['city'])
      assert_equal('CBD', body['classification'])
      assert_equal('Residential', body['zone'])
    end

    def test_create_project_propagates_409_conflict
      # Picker's UI relies on status: 409 to re-prompt; the error
      # envelope's details.name carries the offending value.
      err_body = JSON.generate({
        'error' => {
          'code' => 'conflict',
          'message' => "a project named 'dup' already exists",
          'details' => { 'name' => 'dup' },
        },
      })
      fake = FakeHttp.new(status: 409, body: err_body)

      with_fake(fake) do
        err = assert_raises(EngineClient::EngineError) do
          EngineClient.create_project(
            name: 'dup', city: 'x', classification: 'y', zone: 'z',
          )
        end
        assert_equal(409, err.status)
        assert_equal('conflict', err.code)
        assert_equal({ 'name' => 'dup' }, err.details)
      end
    end

    def test_list_projects_pagination_defaults
      fake = FakeHttp.new(status: 200, body: JSON.generate({ 'items' => [], 'limit' => 100, 'offset' => 0 }))

      with_fake(fake) do
        EngineClient.list_projects
      end

      assert_equal('/projects', captured_uri.path)
      query = captured_uri.query
      # Defaults match the route's _DEFAULT_LIMIT / _MAX_LIMIT.
      assert_match(/limit=100/, query)
      assert_match(/offset=0/, query)
    end

    def test_list_projects_respects_explicit_pagination
      fake = FakeHttp.new(status: 200, body: JSON.generate({ 'items' => [] }))

      with_fake(fake) do
        EngineClient.list_projects(limit: 25, offset: 50)
      end

      query = captured_uri.query
      assert_match(/limit=25/, query)
      assert_match(/offset=50/, query)
    end

    def test_get_project_hits_per_id_path
      row = { 'id' => 7, 'name' => 'mine', 'city' => 'a',
              'classification' => 'b', 'zone' => 'c',
              'created_at' => '2026-05-17T00:00:00Z' }
      fake = FakeHttp.new(status: 200, body: JSON.generate(row))

      with_fake(fake) do
        assert_equal(row, EngineClient.get_project(7))
      end

      assert_equal('/projects/7', captured_uri.path)
      assert_equal('GET', fake.captured.method)
      assert_equal('Bearer test-token', fake.captured['Authorization'])
    end

    def test_get_project_translates_404
      # ensure_project_selected uses 404 as the "stored id is
      # stale" signal — it must come through as e.status == 404.
      err_body = JSON.generate({ 'error' => { 'code' => 'not_found', 'message' => 'gone' } })
      fake = FakeHttp.new(status: 404, body: err_body)

      with_fake(fake) do
        err = assert_raises(EngineClient::EngineError) { EngineClient.get_project(99999) }
        assert_equal(404, err.status)
        assert_equal('not_found', err.code)
      end
    end

    # -- project_id threading on /history endpoints ----------------------

    def test_save_history_threads_project_id_when_present
      archive = { 'report_id' => 'r1', 'response' => { 'ok' => true } }
      fake = FakeHttp.new(status: 201, body: JSON.generate(archive))

      with_fake(fake) do
        EngineClient.save_history({ snapshot_id: 'u' }, project_id: 42)
      end

      req = fake.captured
      assert_equal('POST', req.method)
      assert_equal('/history', captured_uri.path)
      # Engine reads project_id as a Query param, not a body field.
      assert_equal('project_id=42', captured_uri.query)
    end

    def test_save_history_omits_project_id_when_nil
      archive = { 'report_id' => 'r1', 'response' => { 'ok' => true } }
      fake = FakeHttp.new(status: 201, body: JSON.generate(archive))

      with_fake(fake) do
        # Legacy/explicit no-anchor save.
        EngineClient.save_history({ snapshot_id: 'u' })
      end

      # No ?project_id=… — engine falls into the NULL legacy lane.
      assert_nil(captured_uri.query)
      assert_equal('/history', captured_uri.path)
    end

    def test_list_history_threads_project_id_into_query
      fake = FakeHttp.new(status: 200, body: JSON.generate({ 'items' => [], 'total' => 0 }))

      with_fake(fake) do
        EngineClient.list_history(project_id: 7)
      end

      query = captured_uri.query
      assert_match(/project_id=7/, query)
    end

    def test_list_history_drops_nil_project_id
      # When the picker hasn't been used yet, project_id is nil —
      # the query must NOT include "project_id=" so the engine
      # doesn't try to parse the empty/None string.
      fake = FakeHttp.new(status: 200, body: JSON.generate({ 'items' => [], 'total' => 0 }))

      with_fake(fake) do
        EngineClient.list_history
      end

      refute_match(/project_id=/, captured_uri.query)
    end
  end
end
