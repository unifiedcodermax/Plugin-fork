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
require_relative 'limits_cache'
require_relative 'observers/live_validator'
require_relative 'observers/in_design_observer'
require_relative 'geometry/quick_checks'
require_relative 'ui/browser_view'
require_relative 'ui/history_dialog'
require_relative 'ui/login_dialog'
require_relative 'ui/project_picker'
require_relative 'ui/results_dialog'
require_relative 'update_checker'

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
        ::UI.messagebox(
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

      # Non-blocking check for newer releases on GitHub.
      UpdateChecker.check_once
    end

    # Called once a valid JWT is stored in Session. Captures project
    # metadata (once), attaches the live-validate observer, and runs
    # an initial pass so the user sees state immediately.
    def on_authenticated
      Logger.info('authenticated', token_length: Session.token&.length)
      return unless ensure_project_setup
      ensure_project_selected
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

    # -- /history wiring --------------------------------------------------

    # Persist the current model state as an archived run. Stores
    # the returned report_id on Session so "Compare with last save"
    # and "Open last report" know what to point at.
    def save_current_run
      return unless authenticated_and_set_up?
      ensure_project_selected

      snapshot = extract_snapshot
      return unless snapshot

      archive = EngineClient.save_history(snapshot, project_id: Session.project_id)
      report_id = archive['report_id']
      Session.last_report_id = report_id
      Logger.info(
        'history_saved',
        report_id: report_id,
        project_id: Session.project_id,
        ok: archive['response']&.dig('ok'),
      )
      ::UI.messagebox("Saved. report_id: #{report_id[0, 8]}…")
    rescue Geometry::Extractor::ExtractionError => e
      ::UI.messagebox("Could not save: #{e.message}")
    rescue EngineClient::EngineError => e
      Logger.warn('history_save_failed', code: e.code, message: e.message)
      ::UI.messagebox("Save failed: #{e.message}")
    end

    # Open the Recent runs HtmlDialog.
    def show_history
      return unless authenticated_and_set_up?
      UI::HistoryDialog.show
    end

    # Save the current state, then auto-diff it against the prior
    # run for the same project context. Opens the HTML diff in the
    # default browser. This is the marquee "did my last edit make
    # things better or worse?" affordance.
    def compare_with_last_save
      return unless authenticated_and_set_up?
      ensure_project_selected

      snapshot = extract_snapshot
      return unless snapshot

      archive = EngineClient.save_history(snapshot, project_id: Session.project_id)
      report_id = archive['report_id']
      Session.last_report_id = report_id

      html = EngineClient.auto_diff_html(report_id)
      UI::BrowserView.open_html(html, tag: 'compare')
    rescue Geometry::Extractor::ExtractionError => e
      ::UI.messagebox("Could not compare: #{e.message}")
    rescue EngineClient::EngineError => e
      if e.status == 404
        ::UI.messagebox('No prior run exists for this project context yet — this save is your baseline.')
      else
        Logger.warn('history_compare_failed', code: e.code, message: e.message)
        ::UI.messagebox("Compare failed: #{e.message}")
      end
    end

    # Open the HTML render of the most-recently-saved run for this
    # SketchUp session in the default browser. Stays useful even
    # without an active server-side last-save because we cache the
    # id on Session.
    def open_last_report
      return unless authenticated_and_set_up?

      report_id = Session.last_report_id
      unless report_id
        ::UI.messagebox('No saved run yet in this session. Use "Save current run" first.')
        return
      end

      html = EngineClient.get_history_html(report_id)
      UI::BrowserView.open_html(html, tag: "report-#{report_id[0, 8]}")
    rescue EngineClient::EngineError => e
      Logger.warn('history_open_last_failed', code: e.code, message: e.message)
      ::UI.messagebox("Could not open report: #{e.message}")
    end

    # Shared guard for menu actions that need login + project setup.
    def authenticated_and_set_up?
      unless Session.authenticated?
        ::UI.messagebox('Sign in first — use "Planara — Compliance Check".')
        return false
      end
      ensure_project_setup
    end

    # Extract once, returning nil and showing a friendly dialog when
    # the model isn't shaped the way the extractor expects.
    def extract_snapshot
      model = Sketchup.active_model
      Geometry::Extractor.extract(
        model: model,
        project: Session.project,
        parking_slots: Session.project[:parking_slots]
      )
    rescue Geometry::Extractor::ExtractionError => e
      ::UI.messagebox("Could not read the model:\n\n#{e.message}\n\n" \
                      'Name your plot group "Plot" and floor groups "Floor 0", "Floor 1", etc.')
      nil
    end

    # Internal validation step shared between the initial pass and
    # the live-loop observer. When ``noisy`` is true, extraction/
    # transport errors also pop a dialog; otherwise they are pushed
    # to the Results panel's error banner so the architect gets
    # immediate feedback without modal interruptions.
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
      UI::ResultsDialog.update_error(error_type: 'extraction', message: e.message)
      if noisy
        ::UI.messagebox("Could not read the model:\n\n#{e.message}\n\n" \
                        'Name your plot group "Plot" and floor groups "Floor 0", "Floor 1", etc.')
      end
    rescue EngineClient::EngineError => e
      Logger.warn('validate_failed', code: e.code, message: e.message, noisy: noisy)
      UI::ResultsDialog.update_error(error_type: 'engine', message: e.message)
      ::UI.messagebox("Validation failed: #{e.message}") if noisy
    end

    # Live-loop lifecycle -------------------------------------------------

    def start_live_loop
      stop_live_loop

      model = Sketchup.active_model
      return unless model

      # Tier 1: post-gesture full engine validation (unchanged).
      @live_observer = Observers::LiveValidator.new do
        next unless Session.authenticated? && Session.project_ready?
        live_validate(noisy: false)
      end
      model.add_observer(@live_observer)

      # Tier 2: mid-gesture Ruby-side quick checks against cached limits.
      @in_design_observer = Observers::InDesignObserver.new
      model.entities.add_observer(@in_design_observer)

      Logger.info('live_loop_started', tiers: 2)
    end

    def stop_live_loop
      model = Sketchup.active_model

      if @in_design_observer
        @in_design_observer.detach(model)
        @in_design_observer = nil
      end

      if @live_observer
        @live_observer.detach(model)
        @live_observer = nil
      end

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

    # Make sure a regression-tracking project_id is selected for
    # this SketchUp session. Lookup order:
    #   1. Already on Session (set earlier in this session).
    #   2. Stored on the active model's attribute dictionary (a
    #      previously-saved .skp remembering its anchor).
    #   3. Prompt the user via ProjectPicker.
    #
    # Idempotent. Returns the chosen id or nil if the user cancels
    # the picker — callers can proceed without an anchor (saves
    # still work; they just stay in the legacy lane).
    def ensure_project_selected
      return Session.project_id if Session.project_id

      model = Sketchup.active_model
      stored = Session.load_project_id_from_model(model)
      if stored
        # Trust-but-verify: a stored id from an older session might
        # point at a project the user since deleted (or worse, one
        # that now belongs to a different account). Confirm via
        # get_project; on 404, fall through to the picker rather
        # than carry a dangling reference.
        begin
          EngineClient.get_project(stored)
          Session.project_id = stored
          Logger.info('project_id_restored_from_model', project_id: stored)
          return stored
        rescue EngineClient::EngineError => e
          if e.status == 404
            Logger.info('stored_project_id_stale', project_id: stored)
            Session.store_project_id_on_model(model, nil)
          else
            Logger.warn('project_lookup_failed', code: e.code, message: e.message)
            return nil
          end
        end
      end

      chosen = UI::ProjectPicker.pick(project_context: Session.project || {})
      return nil unless chosen

      Session.project_id = chosen
      Session.store_project_id_on_model(model, chosen)
      Logger.info('project_id_selected', project_id: chosen)
      chosen
    end

    # Menu action: explicitly re-prompt the picker even when an id
    # is already set. Useful when a user moves a model between
    # projects mid-session. Clears the in-memory selection first so
    # ensure_project_selected runs the picker path.
    def switch_project
      return unless Session.authenticated?
      Session.project_id = nil
      ensure_project_selected
    end

    def prompt_project_setup
      # Classification maps to Bangalore Building Byelaws 2003 area types:
      #   Heritage → Area A (Intensely Developed Area)
      #   CBD      → Area B (Moderately Developed Area)
      #   HDZ      → Area C (Sparsely Developed Area)
      # FAR, setback, and coverage values are derived from Byelaw Tables 4–6, 10, 13.
      prompts = [
        'City',
        'Classification (Heritage=IntenseDev / CBD=ModerateDev / HDZ=SparseDev)',
        'Zone (Residential / Commercial / Industry)',
        'Overlays (comma-separated, blank for none)',
        'Parking slots provided',
        'Has lift? (yes / no)'
      ]
      defaults = ['Bangalore', 'CBD', 'Residential', '', '0', 'no']
      input = ::UI.inputbox(prompts, defaults, 'Planara — Project setup (Byelaws 2003)')
      return nil unless input

      overlays = input[3].to_s.split(',').map(&:strip).reject(&:empty?)
      has_lift = input[5].to_s.strip.downcase.start_with?('y')
      {
        city: input[0],
        classification: input[1],
        zone: input[2],
        overlays: overlays,
        parking_slots: input[4].to_i,
        has_lift: has_lift,
      }
    end

    def show_validation_result(response)
      UI::ResultsDialog.update(response)

      # Populate limits cache from engine metrics so the in-design
      # observer has authoritative limits to check against during
      # the next tool gesture. Also clear any mid-gesture warnings
      # since the full engine result supersedes them.
      LimitsCache.populate(response)
      UI::ResultsDialog.clear_in_design_warning
      ::Sketchup.set_status_text('', SB_PROMPT) rescue nil
    end

    # Called when SketchUp shuts down. Registered in install_hooks
    # below via Sketchup::AppObserver.
    def shutdown
      Logger.info('plugin_shutting_down')
      stop_live_loop
      UI::ResultsDialog.close
      UI::HistoryDialog.close
      EngineSupervisor.stop
      Session.clear
      LimitsCache.clear
    end

    # Called when the user closes the Live compliance dialog via the
    # window's X button. Tears down the live-loop and clears the
    # project metadata so the next "Planara — Compliance Check"
    # re-prompts for project details (City, Classification, Zone,
    # Overlays, Parking) before running the engine again.
    def on_dialog_closed
      Logger.info('results_dialog_closed_by_user')
      stop_live_loop
      Session.project = nil
      LimitsCache.clear
      UI::ResultsDialog.reset_dialog_ref
    end

    # AppObserver that forwards SketchUp's lifecycle to Boot.shutdown.
    class ShutdownObserver < Sketchup::AppObserver
      def onQuit
        Planara::Boot.shutdown
      end

      def onOpenModel(_model)
        if Planara::Session.authenticated?
          Planara::Boot.start_live_loop
          # Auto-validate the newly-opened model so pre-built SKP
          # files show results immediately without a menu click.
          Planara::Boot.live_validate(noisy: false) if Planara::Session.project_ready?
        end
      end

      def onNewModel(_model)
        if Planara::Session.authenticated?
          Planara::Boot.start_live_loop
          Planara::Boot.live_validate(noisy: false) if Planara::Session.project_ready?
        end
      end
    end

    def install_hooks
      Sketchup.add_observer(ShutdownObserver.new)
    end
  end
end

unless file_loaded?(__FILE__)
  Planara::Boot.install_hooks

  menu = UI.menu('Plugins')
  menu.add_item('Planara — Compliance Check')    { Planara::Boot.activate }
  menu.add_separator
  menu.add_item('Planara — Save current run')    { Planara::Boot.save_current_run }
  menu.add_item('Planara — Recent runs…')        { Planara::Boot.show_history }
  menu.add_item('Planara — Compare with last save') { Planara::Boot.compare_with_last_save }
  menu.add_item('Planara — Open last report in browser') { Planara::Boot.open_last_report }
  menu.add_item('Planara — Switch project…')     { Planara::Boot.switch_project }

  file_loaded(__FILE__)
end
