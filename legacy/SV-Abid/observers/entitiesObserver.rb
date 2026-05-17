
# require_relative 'core/calculations' 
# require_relative 'ui/input_ui' 
 

module SV_Abid
    class AbidEntityObserver < Sketchup::EntitiesObserver
        def initialize
            @last_changed = {}
            @debounce_time = 0.5 # seconds
        end

        def onElementModified(entities, entity)
            return unless entity.respond_to?(:persistent_id)
            pid = entity.persistent_id
            current_time = Time.now.to_f

            # Debounce duplicate events
            return if @last_changed[pid] && (current_time - @last_changed[pid]) < @debounce_time

            @last_changed[pid] = current_time
            Calculations.update_calculations(Sketchup.active_model)
            #UIDisplay.refresh_display
        end

        def onElementAdded(entities, entity)
            return unless entity.respond_to?(:persistent_id)
            @last_changed[entity.persistent_id] = Time.now.to_f
            Calculations.update_calculations(Sketchup.active_model)
            #UIDisplay.refresh_display
        end

        def onElementRemoved(entities, entity)
            return unless entity.respond_to?(:persistent_id)
            @last_changed[entity.persistent_id] = Time.now.to_f
            Calculations.update_calculations(Sketchup.active_model)
            #UIDisplay.refresh_display
        end
    end
end

