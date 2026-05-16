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

    # Called once a valid JWT is stored in Session. Runs the first
    # validation manually; observer-driven re-validation is wired
    # in Sprint 4.
    def on_authenticated
      Logger.info('authenticated', token_length: Session.token&.length)
      run_validation_once
    end

    # Demo path until observers arrive: ensure project metadata is
    # captured, extract a Snapshot, post /validate, render the response.
    def run_validation_once
      ensure_project_setup or return

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
      ::UI.messagebox("Could not read the model:\n\n#{e.message}\n\n" \
                      'Name your plot group "Plot" and floor groups "Floor 0", "Floor 1", etc.')
    rescue EngineClient::EngineError => e
      ::UI.messagebox("Validation failed: #{e.message}")
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
      ok = response['ok']
      violations = response['violations'] || []
      metrics = response['metrics'] || {}

      lines = []
      lines << (ok ? 'PASS — design is compliant.' : "FAIL — #{violations.length} violation(s).")
      lines << ''
      violations.each do |v|
        lines << "  • [#{v['severity']}] #{v['rule_id']}"
        lines << "      #{v['message']}"
      end
      lines << ''
      lines << "FSI: #{metrics['fsi']} (limit #{metrics['max_fsi']})" if metrics['fsi']
      lines << "Rule pack: #{metrics['rule_pack_version']}" if metrics['rule_pack_version']

      ::UI.messagebox(lines.join("\n"))
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
