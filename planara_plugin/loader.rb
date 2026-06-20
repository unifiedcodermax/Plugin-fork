# frozen_string_literal: true

# Top-level extension registrar for Planara. Lives at the root of
# the planara_plugin/ folder so it can be symlinked into SketchUp's
# Plugins directory without dragging the rest of the source tree.
#
# This file is intentionally minimal — it registers the extension
# with SketchUp and defers all real work to Planara::Boot, which is
# only loaded when the user activates the extension.

require 'sketchup.rb'
require 'extensions.rb'

module Planara
  EXTENSION_ID      = 'Planara'
  EXTENSION_NAME    = 'Planara — Building Byelaw Compliance'
  EXTENSION_VERSION = '0.8.2'

  EXTENSION_ROOT    = File.expand_path('planara', __dir__)
  ENTRY_POINT       = File.join(EXTENSION_ROOT, 'boot.rb')

  MIN_SKETCHUP_VERSION = 20 # SketchUp 2020
end

unless file_loaded?(__FILE__)
  if Sketchup.version.to_i < Planara::MIN_SKETCHUP_VERSION
    UI.messagebox(
      "#{Planara::EXTENSION_NAME} requires SketchUp 2020 or later. " \
      "Detected version: #{Sketchup.version}."
    )
  else
    extension = SketchupExtension.new(Planara::EXTENSION_NAME, Planara::ENTRY_POINT)
    extension.description = 'Live validation of building designs against municipal byelaws ' \
                            '(FSI/FAR, setbacks, coverage, parking, zoning overlays).'
    extension.version   = Planara::EXTENSION_VERSION
    extension.creator   = 'Planara'
    extension.copyright = "Copyright (c) #{Time.now.year} Planara. All rights reserved."

    Sketchup.register_extension(extension, true)
  end

  file_loaded(__FILE__)
end
