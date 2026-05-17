require_relative '../config/constants'
require_relative '../helpers/datapoints'

module SV_Abid
  module FSILogic
    extend self
    
    def check_fsi_compliance
      puts "In FSI Compliance"    
      fsi_limit = DataPoints.get(:fsi_limit)
      puts fsi_limit
      return unless fsi_limit
 
      current_fsi = DataPoints.get(:fsi)      
      puts " current FSI :- #{current_fsi}" 
         
      UIDisplay.refresh_display
      show_feedback(current_fsi, fsi_limit)
    end


    def show_feedback(current_fsi, limit)
      puts "in Show feedback"
      if current_fsi.to_f  > limit.to_f
        UI.messagebox("⚠️ FSI Exceeded! Current: #{current_fsi.round(2)} | Limit: #{limit}")
      else
        puts " in show feedback #{current_fsi.to_i  > limit.to_i}"
      end
    end

  end
end
