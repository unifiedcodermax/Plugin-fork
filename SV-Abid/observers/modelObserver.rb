
# require_relative 'core/calculations' 

module SV_Abid
  class AbidModelObserver < Sketchup::ModelObserver  

    def onTransactionStart(model)
      puts "Transaction started: #{model.active_path&.last&.name || 'Top Level'}"
    end

    def onTransactionCommit(model)
      puts "Transaction committed: #{model.active_path&.last&.name || 'Top Level'}"
      Calculations.update_calculations(model)
    end

    def onTransactionUndo(model)
      puts "Transaction undone: #{model.active_path&.last&.name || 'Top Level'}"
      Calculations.update_calculations(model)
    end

    def onTransactionEnd(model)
      puts "Transaction ended in Model Observer....."
      Calculations.update_calculations
      #UIDisplay.refresh_display
    end
    
  end
end


  