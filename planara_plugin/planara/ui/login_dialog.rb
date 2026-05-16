# frozen_string_literal: true

require 'json'

require_relative '../config'
require_relative '../engine_client'
require_relative '../logger'
require_relative '../session'

module Planara
  module UI
    # Login dialog presented to the user when the plugin needs an
    # authenticated session before doing anything useful.
    #
    # Render strategy:
    #   - SketchUp's UI::HtmlDialog hosts a self-contained HTML
    #     file (assets/login.html) — separating markup from Ruby
    #     keeps the dialog editable in any editor with HTML LSP.
    #   - JS calls back into Ruby via sketchup.submit_login(json)
    #     where the payload is {username, password}. Ruby calls
    #     EngineClient.login and pushes status back as inline JS.
    module LoginDialog
      module_function

      ASSET = File.expand_path('assets/login.html', __dir__)

      def show(on_success: nil)
        @on_success = on_success

        @dialog = ::UI::HtmlDialog.new(
          dialog_title: 'Planara — Sign in',
          preferences_key: 'planara.login',
          scrollable: false,
          resizable: false,
          width: 380,
          height: 320,
          style: ::UI::HtmlDialog::STYLE_DIALOG
        )
        @dialog.set_file(ASSET)

        @dialog.add_action_callback('submit_login') do |_, payload_json|
          handle_submit(payload_json)
        end

        @dialog.add_action_callback('cancel_login') do |_, _|
          Logger.info('login_cancelled')
          @dialog.close
        end

        @dialog.show
      end

      # -- callbacks ----------------------------------------------------------

      def handle_submit(payload_json)
        creds = JSON.parse(payload_json)
        username = creds['username'].to_s
        password = creds['password'].to_s

        if username.empty? || password.empty?
          push_status('error', 'Username and password are required.')
          return
        end

        push_status('pending', 'Signing in...')
        Logger.info('login_attempt', username: username)

        EngineClient.login(username: username, password: password)
        Logger.info('login_success', username: username)
        push_status('ok', 'Signed in.')
        @dialog.close

        @on_success&.call
      rescue EngineClient::EngineError => e
        Logger.warn('login_failed', code: e.code, message: e.message)
        msg = e.code == 'authentication_failed' ? 'Invalid credentials.' : e.message
        push_status('error', msg)
      rescue JSON::ParserError => e
        Logger.error('login_payload_invalid', error: e.message)
        push_status('error', 'Internal error: malformed payload.')
      end

      def push_status(kind, message)
        return unless @dialog

        # JSON.generate handles quoting so we never inject HTML.
        js = "Planara.onStatus(#{JSON.generate({ kind: kind, message: message })});"
        @dialog.execute_script(js)
      end
    end
  end
end
