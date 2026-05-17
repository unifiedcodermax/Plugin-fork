
# require_relative 'ui/input_ui' 

module SV_Abid

    class AbidAppObserver < Sketchup::AppObserver
        def onNewModel(model)
            puts "new model creation...."
            model.add_observer(AbidModelObserver.new)
            model.entities.add_observer(AbidEntityObserver.new)
            model.tools.add_observer(AbidToolsObserver.new)
            UIInput.show_input_dialog
        end

        def onOpenModel(model)
            puts "existing model opened...."
            model.add_observer(AbidModelObserver.new)
            model.entities.add_observer(AbidEntityObserver.new)
            model.tools.add_observer(AbidToolsObserver.new)
            UIInput.show_input_dialog
        end  
    end
end