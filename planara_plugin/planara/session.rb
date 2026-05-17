# frozen_string_literal: true

module Planara
  # Holds plugin-side session state: the JWT, plus the project
  # metadata the user enters once and the live-validate loop reuses
  # on every model commit (no re-prompting per edit).
  #
  # Single module-level instance is fine: SketchUp is a single-user
  # desktop app. A class-with-instance would be overkill.
  module Session
    module_function

    def token
      @token
    end

    def token=(value)
      @token = value
    end

    def clear
      @token = nil
      @project = nil
      @project_id = nil
      @last_report_id = nil
    end

    def authenticated?
      !@token.nil? && !@token.empty?
    end

    # @return [Hash{String => String}] headers to attach to engine requests.
    def auth_headers
      authenticated? ? { 'Authorization' => "Bearer #{@token}" } : {}
    end

    # Canonical project metadata for the current SketchUp model:
    # { city:, classification:, zone:, overlays:, parking_slots: }.
    # nil until the user completes the project-setup prompt.
    def project
      @project
    end

    def project=(value)
      @project = value
    end

    def project_ready?
      p = @project
      !p.nil? && !p[:city].to_s.empty? &&
        !p[:classification].to_s.empty? && !p[:zone].to_s.empty?
    end

    # Most-recently-saved report_id for the current SketchUp
    # session. Powers "Open last report in browser" — only valid
    # for this process; we deliberately don't persist it across
    # restarts so we never point at a stale row after a wipe.
    def last_report_id
      @last_report_id
    end

    def last_report_id=(value)
      @last_report_id = value
    end

    # Currently-selected Project id on the engine side. Threaded
    # through save_history / list_history so this session's runs
    # are anchored to one regression-tracking lane.
    #
    # Persisted per-SketchUp-model via the model's attribute
    # dictionary (see ``load_project_id_from_model`` /
    # ``store_project_id_on_model``) so reopening a .skp picks up
    # the same anchor automatically. nil means "no project
    # selected yet" — saves still work, they just stay in the
    # legacy NULL lane on the engine.
    def project_id
      @project_id
    end

    def project_id=(value)
      @project_id = value
    end

    # SketchUp model attribute dictionary name. Scoped under
    # 'Planara' so we don't collide with the user's own custom
    # attributes, and keyed by 'project_id' inside that dict.
    MODEL_ATTR_DICT = 'Planara'
    MODEL_ATTR_PROJECT_ID = 'project_id'

    # Read a previously-stored project_id off ``model``. Returns
    # nil when the model has never been associated with a project
    # (or the dictionary is missing). Defensive against models
    # that store the id as a string instead of an int — the
    # engine accepts both via FastAPI's Query coercion, but we
    # prefer ints internally.
    def load_project_id_from_model(model)
      return nil unless model
      raw = model.get_attribute(MODEL_ATTR_DICT, MODEL_ATTR_PROJECT_ID, nil)
      return nil if raw.nil?
      Integer(raw)
    rescue ArgumentError, TypeError
      nil
    end

    # Persist ``id`` on ``model``'s attribute dictionary so future
    # opens of this .skp restore the same project anchor. Pass nil
    # to clear the stored id (the picker uses this when the user
    # explicitly unsets the project).
    def store_project_id_on_model(model, id)
      return unless model
      model.set_attribute(MODEL_ATTR_DICT, MODEL_ATTR_PROJECT_ID, id)
    end
  end
end
