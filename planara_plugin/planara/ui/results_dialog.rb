# frozen_string_literal: true

require 'json'

require_relative '../logger'

module Planara
  module UI
    # Live results dialog shown alongside the SketchUp model. Stays
    # open across many validations; ``update`` pushes new state via
    # execute_script. Replaces the modal UI.messagebox demo path.
    #
    # The dialog is non-modal (STYLE_DIALOG) so the user keeps
    # editing the model while it's visible.
    module ResultsDialog
      module_function

      ASSET = File.expand_path('assets/results.html', __dir__)

      # Lazy-instantiate. Re-entry just brings the existing dialog
      # to the front and re-pushes the last payload.
      def show
        ensure_dialog
        @dialog.show
        push(@last_payload) if @last_payload
      end

      # Push a validation response into the dialog. Builds the
      # dialog on first call so callers don't have to think about
      # ordering.
      def update(response)
        ensure_dialog
        @last_payload = response
        push(response) if @dialog.visible?
      end

      # Push an error state into the dialog.  The banner appears
      # at the top of the panel and auto-clears on the next
      # successful ``update``.
      #
      # @param error_type [String] "extraction" or "engine"
      # @param message [String] human-readable error description
      def update_error(error_type:, message:)
        ensure_dialog
        @last_error = { error_type: error_type, message: message }
        push_error(@last_error) if @dialog.visible?
      end

      def close
        @dialog&.close
        @dialog = nil
        @last_payload = nil
        @last_error = nil
      end

      # -- internals -----------------------------------------------------------

      def ensure_dialog
        return if @dialog

        @dialog = ::UI::HtmlDialog.new(
          dialog_title: 'Planara — Live compliance',
          preferences_key: 'planara.results',
          scrollable: true,
          resizable: true,
          width: 560,
          height: 420,
          style: ::UI::HtmlDialog::STYLE_DIALOG
        )
        @dialog.set_file(ASSET)

        # Re-push state once the page is ready (set_file is async on
        # macOS — a push fired before DOM-ready is silently lost).
        @dialog.add_action_callback('ready') do |_, _|
          push(@last_payload) if @last_payload
          push_error(@last_error) if @last_error
        end
      end

      def push(payload)
        return unless @dialog && payload
        js = "Planara.onResult(#{JSON.generate(payload)});"
        @dialog.execute_script(js)
      rescue StandardError => e
        Planara::Logger.warn('results_push_failed', error: e.message)
      end

      def push_error(error)
        return unless @dialog && error
        js = "Planara.onError(#{JSON.generate(error)});"
        @dialog.execute_script(js)
      rescue StandardError => e
        Planara::Logger.warn('results_push_error_failed', error: e.message)
      end
    end
  end
end
