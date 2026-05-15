require 'sketchup.rb'
require 'json'

require_relative 'core/abid_fsi'
require_relative 'core/abid_setback'
require_relative 'helpers/datapoints'
require_relative 'Observers/Observer'
require_relative 'config/constants'

module SV_Abid
  module UIManager
    extend self

    @@dialog = nil  

   
    DataPoints.reset_data

    def self.setup
      prompts = ["Classification(CBD/Heritage/HDZ)","Zone (Residential/Commercial/Industrial/Public & Semi public):", "Plot Area in sq.m:"]
      defaults = ["Heritage","Residential", "0"]
      input = UI.inputbox(prompts, defaults, "Project Setup")
      return unless input
      locClass = input[0]
      zone = input[1]
      pa = input[2].to_f
      if pa <= 0
        UI.messagebox("Invalid plot area!")
        return
      end

      DataPoints.set(:locationClassification, locClass)
      DataPoints.set(:zone,zone)
      DataPoints.set(:plot_area,pa)

      self.show_ui      

      SetBack.get_setbackLimit
      puts "done with get setbacklimit in start....."
      FSILogic.check_fsi_compliance
      puts "done with get check_fsi_compliance in start....."
     
     
      #UI.messagebox("Live Compliance Checker started for #{@zone}. Plot area: #{@plot_area} m²")
    end


    def self.show_ui
      if @@dialog && @@dialog.visible?
        @@dialog.bring_to_front
      else
       
          # Use HtmlDialog for SketchUp 2018 and later
          @@dialog = UI::HtmlDialog.new(
            dialog_title: ProjectConstants::PLUGIN_NAME,
            preferences_key: "FSIOverlayPrefs",
            scrollable: true,
            resizable: true,
            width: 500,
            height: 300,
            style: UI::HtmlDialog::STYLE_UTILITY
          )
          @@dialog.set_file(File.join(__dir__, 'ui', 'dialog.html'))

          @@dialog.set_on_closed {
           @@dialog = nil  # Reset when user closes the dialog
          }

        # @@dialog.add_action_callback("update_settings") do |_, data|
        #     parsed = JSON.parse(data)
        
        #     DataPoints.set(:locationClassification, parsed['locationClassification'])
        #     DataPoints.set(:zone, parsed['zone'])
        #     DataPoints.set(:fsi_mode, parsed['fsi_mode'])
             
          #FSILogic.update_settings(parsed)
        #end
      
        @@dialog.show
        #self.update_panel
       
        
      end
    end

    def self.update_panel
      puts @@dialog.visible?
      if @@dialog && @@dialog.visible? # check if dialog is visible before updating panel
        puts "updating panel...."
         puts "#{DataPoints.get(:locationClassification)} #{Sketchup.active_model.shadow_info["City"]|| "Not Set"} #{DataPoints.get(:zone)} #{DataPoints.get(:plot_area)} #{DataPoints.get(:build)}"
         puts "Limit: #{DataPoints.get(:fsi_limit)} #{DataPoints.get(:fsi)}  Setback Limit: #{DataPoints.get(:setback_limit)}"
         js = <<-JS    
          document.getElementById('locClassification').innerText =  '#{DataPoints.get(:locationClassification)}';
          document.getElementById('location').innerText = '#{Sketchup.active_model.shadow_info["City"]|| "Not Set"}';
          document.getElementById('zone').innerText = '#{DataPoints.get(:zone)}';
          document.getElementById('plot_area').innerText = '#{DataPoints.get(:plot_area)} m²'; 
          document.getElementById('build_area').innerText = '#{DataPoints.get(:build)} m²';
          document.getElementById('current_fsi').innerText = "Limit: #{DataPoints.get(:fsi_limit)} \\n" +
                    "current FSI: #{DataPoints.get(:fsi)}";
          document.getElementById('setbacks').innerText = "Setback Limit: #{DataPoints.get(:setback_limit)}";
        JS
        @@dialog.execute_script(js) if @@dialog
        puts "done...."
       
      else
        puts "Dialong not initialized or not visible..."
      end

    end
      
    
    unless file_loaded?(__FILE__)
      UI.menu("Plugins").add_item(ProjectConstants::PLUGIN_NAME) {
        #self.show_ui
        self.setup
      }
      file_loaded(__FILE__)
    end
  end
end
