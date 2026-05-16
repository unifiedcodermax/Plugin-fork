# frozen_string_literal: true

# Planara — boot entry point.
#
# This file is the `entry_point` passed to SketchupExtension.new in
# loader.rb. SketchUp loads it once when the user enables the
# extension in the Preferences dialog (or immediately if registered
# with load_at_start: true).
#
# It MUST be safe to require: no dialogs, no network calls, no
# observer attachment at load time. All of that happens inside
# Planara::Boot.activate, which is wired to the Plugins menu so
# the user explicitly opts in.

require_relative 'config'
require_relative 'logger'
require_relative 'session'
require_relative 'engine_client'
require_relative 'engine_supervisor'
require_relative 'ui/login_dialog'

module Planara
  module Boot
    module_function

    # Called when the user clicks the Planara menu item. Idempotent:
    # subsequent calls just bring the dialog to front (login UI and
    # observer wiring land in Sprint 2).
    def activate
      Logger.info('plugin_activating', summary: Config.summary)

      begin
        EngineSupervisor.start
      rescue StandardError => e
        UI.messagebox(
          "Planara could not start its compliance engine:\n\n#{e.message}\n\n" \
          "Make sure the planara-engine command is installed and on PATH " \
          "(or set PLANARA_ENGINE_CMD)."
        )
        return
      end

      if Session.authenticated?
        on_authenticated
      else
        UI::LoginDialog.show(on_success: method(:on_authenticated))
      end
    end

    # Called once a valid JWT is stored in Session. Sprint 3 will
    # take over this hook to attach observers and show the live
    # results panel. For now it confirms the round-trip.
    def on_authenticated
      Logger.info('authenticated', token_length: Session.token&.length)
      ::UI.messagebox(
        "Signed in to Planara.\n\n" \
        "Live validation and observers will arrive in Sprint 3."
      )
    end

    # Called when SketchUp shuts down. Registered in install_hooks
    # below via Sketchup::AppObserver.
    def shutdown
      Logger.info('plugin_shutting_down')
      EngineSupervisor.stop
      Session.clear
    end

    # AppObserver that forwards SketchUp's lifecycle to Boot.shutdown.
    class ShutdownObserver < Sketchup::AppObserver
      def onQuit
        Planara::Boot.shutdown
      end
    end

    def install_hooks
      Sketchup.add_observer(ShutdownObserver.new)
    end
  end
end

unless file_loaded?(__FILE__)
  Planara::Boot.install_hooks

  UI.menu('Plugins').add_item('Planara — Compliance Check') { Planara::Boot.activate }

  file_loaded(__FILE__)
end
