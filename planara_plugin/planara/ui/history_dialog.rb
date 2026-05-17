# frozen_string_literal: true

require 'json'

require_relative '../logger'
require_relative '../engine_client'
require_relative '../session'
require_relative 'browser_view'

module Planara
  module UI
    # "Recent runs" browser. Pulls the user's history list from the
    # engine and renders each row with actions:
    #   - Open               → fetch /history/{id}/html, open in browser
    #   - vs prior           → fetch /history/{id}/diff/html, open in browser
    #   - Compare selected   → tick two rows, /history/diff/html?from=&to=
    #
    # Refreshes on demand (button) rather than on every model edit —
    # the live results dialog handles real-time. This one is the
    # archive.
    module HistoryDialog
      module_function

      ASSET = File.expand_path('assets/history.html', __dir__)

      def show
        ensure_dialog
        @dialog.show
        refresh
      end

      def close
        @dialog&.close
        @dialog = nil
      end

      # -- internals -----------------------------------------------------------

      def ensure_dialog
        return if @dialog

        @dialog = ::UI::HtmlDialog.new(
          dialog_title: 'Planara — Recent runs',
          preferences_key: 'planara.history',
          scrollable: true,
          resizable: true,
          width: 780,
          height: 480,
          style: ::UI::HtmlDialog::STYLE_DIALOG
        )
        @dialog.set_file(ASSET)

        @dialog.add_action_callback('ready')         { |_, _| refresh }
        @dialog.add_action_callback('refresh')       { |_, _| refresh }
        @dialog.add_action_callback('open_report')   { |_, id| open_report(id) }
        @dialog.add_action_callback('auto_diff')     { |_, id| open_auto_diff(id) }
        @dialog.add_action_callback('explicit_diff') { |_, from, to| open_explicit_diff(from, to) }
      end

      def refresh
        # Scope to the currently-selected project so the picker
        # acts as a per-project history view. When no project is
        # set, fall back to all-of-my-runs (the legacy behavior).
        rows = EngineClient.list_history(
          limit: 50,
          offset: 0,
          project_id: Session.project_id,
        )
        push_rows(rows)
      rescue EngineClient::EngineError => e
        Logger.warn('history_list_failed', code: e.code, message: e.message)
        push_error("Could not load history: #{e.message}")
      end

      def open_report(report_id)
        html = EngineClient.get_history_html(report_id)
        BrowserView.open_html(html, tag: "report-#{short(report_id)}")
      rescue EngineClient::EngineError => e
        Logger.warn('history_open_failed', report_id: report_id, message: e.message)
        ::UI.messagebox("Could not open report: #{e.message}")
      end

      def open_auto_diff(report_id)
        html = EngineClient.auto_diff_html(report_id)
        BrowserView.open_html(html, tag: "autodiff-#{short(report_id)}")
      rescue EngineClient::EngineError => e
        # 404 with no prior is the common case — surface it nicely.
        if e.status == 404
          ::UI.messagebox('No prior run exists for this project context — this is your baseline.')
        else
          Logger.warn('history_autodiff_failed', report_id: report_id, message: e.message)
          ::UI.messagebox("Could not compute diff: #{e.message}")
        end
      end

      def open_explicit_diff(from_id, to_id)
        html = EngineClient.explicit_diff_html(from_id, to_id)
        BrowserView.open_html(html, tag: "diff-#{short(from_id)}-#{short(to_id)}")
      rescue EngineClient::EngineError => e
        Logger.warn('history_diff_failed', from: from_id, to: to_id, message: e.message)
        ::UI.messagebox("Could not compute diff: #{e.message}")
      end

      def push_rows(payload)
        return unless @dialog
        js = "Planara.onRows(#{JSON.generate(payload)});"
        @dialog.execute_script(js)
      end

      def push_error(message)
        return unless @dialog
        js = "Planara.onError(#{JSON.generate(message)});"
        @dialog.execute_script(js)
      end

      def short(report_id)
        report_id.to_s[0, 8]
      end
    end
  end
end
