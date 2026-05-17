require 'sketchup.rb'
require 'extensions.rb'
 
module SV_Abid
    EXTENSION_ID  = "SV-Abid"
    EXTENSION_NAME = 'Abid Building by laws (Bangalore)'
    EXTENSION_ROOT = File.dirname(__FILE__)
    STARTUP_FILE = File.join(EXTENSION_ROOT, 'SV-Abid/main.rb')

    unless defined?('Abid Building by laws (Bangalore)'::EXTENSION)
        if Sketchup.version.to_i < 20
            UI.messagebox("#{EXTENSION_NAME} - extension requires SketchUp 2020 or later.")
            raise LoadError, "Unsupported SketchUp version"
        end

        # Register the extension with SketchUp.
        extension = SketchupExtension.new('Abid Building by laws (Bangalore)', 'SV-Abid/main.rb')
        extension.description = 'A custom project plugin for Abid Building by laws (Bangalore)'
        extension.version = '1.0.0'
        extension.creator = 'Shraddha Group of companies'
        extension.copyright = 'Copyright © 2025 Sharddha Group of Companies. All rights reserved.'

        Sketchup.register_extension(extension, true)
    end

     # Menu item to show display window
    unless file_loaded?(__FILE__)
        menu = UI.menu('Plugins')
        #menu.add_item('Abid Building by laws (Bangalore)') { UIDisplay.show_display_window }
        menu.add_item('Abid Building by laws (Bangalore)') { SV_Abid.init_plugin }
        file_loaded(__FILE__)
    end
   
end