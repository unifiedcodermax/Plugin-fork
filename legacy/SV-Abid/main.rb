require_relative 'Observers/appObserver'
require_relative 'Observers/modelobserver'
require_relative 'Observers/entitiesObserver'
require_relative 'Observers/toolsObserver'
require_relative 'core/calculations' 
require_relative 'ui/input_ui'
require_relative 'ui/display_ui'

module SV_Abid  
    def self.init_plugin
        @last_bbox = nil
        # Initialize observers
        Sketchup.add_observer(AbidAppObserver.new)
        Sketchup.active_model.add_observer(AbidModelObserver.new)
        #Sketchup.active_model.entities.add_observer(AbidEntityObserver.new)
        Sketchup.active_model.tools.add_observer(AbidToolsObserver.new)

        # Start timer for bounding box checks
        #start_bounding_box_timer

        # Show input UI for new/open model
        UIInput.show_input_dialog if Sketchup.active_model
    end

    # Timer for periodic bounding box checks
    def self.start_bounding_box_timer  
        UI.start_timer(1.0, true) do
        model = Sketchup.active_model
        next unless model
        current_bbox = model.bounds
        unless @last_bbox == current_bbox
            puts "in start  bounding box timer #{@last_bbox}"
            Calculations.update_calculations
            #UIDisplay.refresh_display
        end
        @last_bbox = current_bbox.dup
        end
    end

    #SV_Abid.init_plugin
   
end