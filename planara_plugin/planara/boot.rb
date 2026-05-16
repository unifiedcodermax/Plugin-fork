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
require_relative 'geometry/extractor'
require_relative 'observers/live_validator'
require_relative 'ui/login_dialog'
require_relative 'ui/results_dialog'

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

    # Called once a valid JWT is stored in Session. Captures project
    # metadata (once), attaches the live-validate observer, and runs
    # an initial pass so the user sees state immediately.
    def on_authenticated
      Logger.info('authenticated', token_length: Session.token&.length)
      return unless ensure_project_setup
      UI::ResultsDialog.show
      start_live_loop
      live_validate
    end

    # One-shot validation pass. Used for the initial render after
    # login and (later) from a menu item. Surfaces extraction errors
    # via a dialog because this is a user-triggered action.
    def run_validation_once
      ensure_project_setup or return
      live_validate(noisy: true)
    end

    # Internal validation step shared between the initial pass and
    # the live-loop observer. When ``noisy`` is true, extraction/
    # transport errors pop a dialog; otherwise they only log, so the
    # observer doesn't spam dialogs during normal editing.
    def live_validate(noisy: false)
      model = Sketchup.active_model
      snapshot = Geometry::Extractor.extract(
        model: model,
        project: Session.project,
        parking_slots: Session.project[:parking_slots]
      )
      Logger.info(
        'snapshot_extracted',
        floors: snapshot[:building][:floors].length,
        plot_area_m2: snapshot[:plot][:area_m2]&.round(2),
        parking_slots: snapshot[:building][:parking_slots_provided],
        overlays: snapshot[:project][:overlays]
      )

      response = EngineClient.validate(snapshot)
      show_validation_result(response)
    rescue Geometry::Extractor::ExtractionError => e
      Logger.warn('extract_failed', error: e.message, noisy: noisy)
      if noisy
        ::UI.messagebox("Could not read the model:\n\n#{e.message}\n\n" \
                        'Name your plot group "Plot" and floor groups "Floor 0", "Floor 1", etc.')
      end
    rescue EngineClient::EngineError => e
      Logger.warn('validate_failed', code: e.code, message: e.message, noisy: noisy)
      ::UI.messagebox("Validation failed: #{e.message}") if noisy
    end

    # Live-loop lifecycle -------------------------------------------------

    def start_live_loop
      return if @live_observer

      model = Sketchup.active_model
      return unless model

      @live_observer = Observers::LiveValidator.new do
        next unless Session.authenticated? && Session.project_ready?
        live_validate(noisy: false)
      end
      model.add_observer(@live_observer)
      Logger.info('live_loop_started')
    end

    def stop_live_loop
      return unless @live_observer
      @live_observer.detach(Sketchup.active_model)
      @live_observer = nil
      Logger.info('live_loop_stopped')
    end

    # Re-prompt only when Session has no project yet; the live loop
    # (Sprint 6) reuses Session.project across many validations.
    def ensure_project_setup
      return true if Session.project_ready?

      project = prompt_project_setup
      return false unless project

      Session.project = project
      Logger.info('project_set', project: project)
      true
    end

    def prompt_project_setup
      prompts = [
        'City',
        'Classification (Heritage / CBD / HDZ)',
        'Zone (Residential / Commercial / Industry)',
        'Overlays (comma-separated, blank for none)',
        'Parking slots provided'
      ]
      defaults = ['Bangalore', 'CBD', 'Residential', '', '0']
      input = ::UI.inputbox(prompts, defaults, 'Planara — Project setup')
      return nil unless input

      overlays = input[3].to_s.split(',').map(&:strip).reject(&:empty?)
      {
        city: input[0],
        classification: input[1],
        zone: input[2],
        overlays: overlays,
        parking_slots: input[4].to_i,
      }
    end

    def show_validation_result(response)
      UI::ResultsDialog.update(response)
    end

    # Called when SketchUp shuts down. Registered in install_hooks
    # below via Sketchup::AppObserver.
    def shutdown
      Logger.info('plugin_shutting_down')
      stop_live_loop
      UI::ResultsDialog.close
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
