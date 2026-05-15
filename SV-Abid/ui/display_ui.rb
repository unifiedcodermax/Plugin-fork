require_relative '../helpers/datapoints'



module SV_Abid
    module UIDisplay
    def self.show_display_window
      @html_dialog ||= create_dialog
      @html_dialog.show
      refresh_display
    end

    def self.create_dialog 
      dialog = UI::HtmlDialog.new({
          dialog_title: ProjectConstants::PLUGIN_NAME,
          preferences_key: "FSIOverlayPrefs",
          scrollable: true,
          resizable: true,
          width: 500,
          height: 300,
          style: UI::HtmlDialog::STYLE_UTILITY
      }) 

      html = <<-HTML
      <!DOCTYPE html>
      <html>
      <head>
        <style>
          body { font-family: Arial, sans-serif; padding: 10px; }
          .info { margin-bottom: 10px; }
          .label { font-weight: bold; }
        </style>
      </head>
      <body>
        <div class='info'><span class='label'>Classification:</span> <span id='lblClassification'></span></div>        
        <div class='info'><span class='label'>Zone:</span> <span id='lblZone'></span></div>
        <div class='info'><span class='label'>Plot Area:</span> <span id='lblPlot_area'></span> sq m</div>        
        <div class='info'><span class='label'>Total Height:</span> <span id='lblTotal_height'></span>  m</div>
        <div class='info'><span class='label'>Built up Area:</span> <span id='lblBuilt_up_area'></span> sq m</div>
        <div class='info'><span class='label'>FSI Limit / Current FSI:</span> <span id='lblFSI'></span></div>
        <div class='info'><span class='label'>Setback Limit:</span> <span id='lblSetback'></span></div>
      </body>
      </html>
      HTML

      dialog.set_html(html)
      dialog
    end

    def self.refresh_display
      UIDisplay.show_display_window unless @html_dialog && @html_dialog.visible? 
      puts "in refresh display...."
      @html_dialog.execute_script("document.getElementById('lblClassification').innerText = '#{DataPoints.get(:locationClassification)}'")
      @html_dialog.execute_script("document.getElementById('lblZone').innerText = '#{DataPoints.get(:zone)}'")
      @html_dialog.execute_script("document.getElementById('lblPlot_area').innerText = '#{DataPoints.get(:plot_area)}'")     
      @html_dialog.execute_script("document.getElementById('lblTotal_height').innerText = '#{DataPoints.get(:height)}'")
      @html_dialog.execute_script("document.getElementById('lblBuilt_up_area').innerText = '#{DataPoints.get(:build)}'")
      @html_dialog.execute_script("document.getElementById('lblFSI').innerText = 'Limit: #{DataPoints.get(:fsi_limit)} \\n Current FSI: #{DataPoints.get(:fsi)}'")
      @html_dialog.execute_script("document.getElementById('lblSetback').innerText = '#{DataPoints.get(:setback_limit)}'")

      
      

    end
  end
end

