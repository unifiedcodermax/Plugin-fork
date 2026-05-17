# frozen_string_literal: true

require_relative '../logger'
require_relative '../engine_client'
require_relative '../session'

module Planara
  module UI
    # Project picker — runs once per SketchUp session after login.
    #
    # Lets the user pick an existing Project on the engine side
    # (returns its id) or create a new one ("+ New project…"). The
    # selected id is threaded through save_history / list_history
    # so every run is anchored to the same regression-tracking
    # lane, regardless of whether the user later re-zones the
    # design.
    #
    # Implemented as a sequence of ``UI.inputbox`` prompts rather
    # than an HtmlDialog. Two reasons: (a) the dialog needs to
    # block — Boot.on_authenticated can't start the live loop
    # until we know which project to anchor to — and HtmlDialog is
    # async; (b) the input here is a short numbered list, not
    # something that benefits from a rich UI.
    module ProjectPicker
      module_function

      # Cap the picker list so a power-user with 200 projects
      # doesn't see an unreadable wall of names. The picker is
      # short-term; a Sprint-14 full HtmlDialog browser will lift
      # this cap.
      PICKER_LIMIT = 20

      # Run the picker. Returns the chosen project_id (Integer) or
      # nil if the user cancels at any point. Caller is responsible
      # for storing the result on Session / the model attribute
      # dictionary; the picker itself is stateless so it can be
      # invoked from menu items too.
      #
      # ``project_context`` is the {city:, classification:, zone:}
      # captured by the existing project-setup prompt — used to
      # pre-fill the "create new" dialog so the user doesn't have
      # to retype.
      def pick(project_context:)
        envelope = fetch_projects
        return nil unless envelope

        items = envelope['items'] || []
        choice = prompt_choice(items)
        return nil unless choice

        if choice == :new
          create_new(project_context: project_context)
        else
          # choice is the existing project's id (Integer).
          choice
        end
      end

      # -- internals -----------------------------------------------------------

      def fetch_projects
        EngineClient.list_projects(limit: PICKER_LIMIT)
      rescue EngineClient::EngineError => e
        Logger.warn('project_picker_list_failed', code: e.code, message: e.message)
        ::UI.messagebox("Could not load projects: #{e.message}")
        nil
      end

      # Build the dropdown shown to the user. The first entry is
      # always "+ New project…"; subsequent entries are existing
      # projects, labelled with name + context so duplicates are
      # distinguishable.
      #
      # Returns :new, an Integer id, or nil on cancel.
      def prompt_choice(items)
        labels = ['+ New project…'] + items.map { |it| format_label(it) }
        prompts = ['Project']
        defaults = [labels.first]
        lists = [labels.join('|')]

        result = ::UI.inputbox(prompts, defaults, lists, 'Planara — Select project')
        return nil unless result

        picked_label = result[0]
        return :new if picked_label == labels.first

        index = labels.index(picked_label) - 1
        items[index]['id']
      end

      def format_label(item)
        # "5th Main — Bangalore / CBD / Residential"
        ctx = [item['city'], item['classification'], item['zone']].compact.join(' / ')
        ctx.empty? ? item['name'].to_s : "#{item['name']} — #{ctx}"
      end

      # Prompt for a new project's name; reuse the existing
      # project_context for the city/classification/zone fields
      # (the picker is invoked AFTER ensure_project_setup, so we
      # already have those). Returns the new id, or nil on cancel
      # / unrecoverable error. A 409 conflict re-prompts so the
      # user can pick a different name without restarting.
      def create_new(project_context:)
        loop do
          name = ::UI.inputbox(
            ['Project name'],
            [''],
            'Planara — New project'
          )
          return nil unless name

          name_value = name[0].to_s.strip
          if name_value.empty?
            ::UI.messagebox('Project name cannot be empty.')
            next
          end

          begin
            row = EngineClient.create_project(
              name: name_value,
              city: project_context[:city].to_s,
              classification: project_context[:classification].to_s,
              zone: project_context[:zone].to_s,
            )
            Logger.info('project_created', id: row['id'], name: row['name'])
            return row['id']
          rescue EngineClient::EngineError => e
            if e.status == 409
              # Per-user name collision — re-prompt. The detail
              # carries the offending name so we can surface it
              # explicitly.
              ::UI.messagebox("A project named #{name_value.inspect} already exists. Pick a different name.")
              next
            end
            Logger.warn('project_create_failed', code: e.code, message: e.message)
            ::UI.messagebox("Could not create project: #{e.message}")
            return nil
          end
        end
      end
    end
  end
end
