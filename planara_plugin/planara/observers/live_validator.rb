# frozen_string_literal: true

require_relative '../logger'

module Planara
  module Observers
    # Sketchup::ModelObserver that triggers a debounced extract +
    # /validate after each transaction commit/undo.
    #
    # SketchUp fires several commits during a single user gesture
    # (drag-an-edge can produce dozens). A naive observer would post
    # one request per commit; we collapse them with a trailing-edge
    # debounce: the first commit in a quiet window schedules a
    # UI.start_timer; each subsequent commit cancels and reschedules
    # it; only the last commit before the timer expires fires the
    # callback.
    class LiveValidator < Sketchup::ModelObserver
      DEBOUNCE_S = 0.5

      def initialize(&on_fire)
        super()
        @on_fire = on_fire
        @timer_id = nil
      end

      def onTransactionCommit(_model)
        schedule
      end

      def onTransactionUndo(_model)
        schedule
      end

      # Detach the observer. Idempotent — SketchUp's remove_observer
      # raises if the observer is already gone, so we swallow.
      def detach(model)
        model.remove_observer(self) if model
      rescue StandardError
        nil
      ensure
        cancel_timer
      end

      def schedule
        cancel_timer
        @timer_id = ::UI.start_timer(DEBOUNCE_S, false) do
          @timer_id = nil
          begin
            @on_fire.call
          rescue StandardError => e
            Planara::Logger.error(
              'live_validator_callback_error',
              error: e.message,
              backtrace: e.backtrace&.first(5)
            )
          end
        end
      end

      def cancel_timer
        return unless @timer_id
        ::UI.stop_timer(@timer_id) rescue nil
        @timer_id = nil
      end
    end
  end
end
