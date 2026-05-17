
# require_relative 'core/calculations' 

module SV_Abid
        
    class AbidToolsObserver < Sketchup::ToolsObserver
        # def onToolStateChanged(tools, tool_name, tool_id)
        #     puts [tools, tool_name, tool_id, state].inspect
        #     # Track Push/Pull and other tools
        #     if tool_name == "PushPullTool"
        #         puts "push pull trackinng...."
        #         Calculations.update_calculations(Sketchup.active_model)
        #         UIDisplay.refresh_display
        #     end
        # end

        

    end
end