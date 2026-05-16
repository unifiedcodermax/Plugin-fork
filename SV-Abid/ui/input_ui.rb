require_relative '../helpers/datapoints'
require_relative '../core/calculations' 

module SV_Abid
  module UIInput
      def self.show_input_dialog
        model = Sketchup.active_model
        prompts = [
          "Location Classification(CBD/Heritage/HDZ)",
          "Zone (Residential/Commercial/Industrial/Public & Semi public):",
          "Plot Area (sq.m):",
          "Overlays (comma-separated, blank for none):"
        ]
        defaults = ['CBD', 'Residential', '0.0', '']
        input = UI.inputbox(prompts, defaults, 'Abid setup')

        puts "input received -> #{input}"
        return unless input

        DataPoints.set(:locationClassification, input[0])
        DataPoints.set(:zone, input[1])
        DataPoints.set(:plot_area, input[2].to_f)
        # Split on commas, strip whitespace, drop empty tokens.
        overlays = input[3].to_s.split(',').map(&:strip).reject(&:empty?)
        DataPoints.set(:overlays, overlays)

        # get the limits for FSI & Setbacks and store
        DataPoints.getFSILimit
        DataPoints.getSetbackLimit

        puts "about to call calculations"
        Calculations.update_calculations(Sketchup.active_model)

      end
    end
end
