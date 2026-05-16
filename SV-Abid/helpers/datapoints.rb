require_relative '../config/constants'
require_relative 'hash_utils'
 
 module SV_Abid
    module DataPoints 
        extend self
       
        @data_store = {
          plot_area: 0.0,
          build: 0.0,
          fsi: 0.0,
          height: 0.0,
          floors: 0,
          standard_floor_height: 3.0,  # in meters
          fsi_limit: 0.0,
          locationClassification: "",
          zone: "",
          setback_limit: 0.0,
          overlays: []
        }
        

        def reset_data
            puts "in reset_data"        
            set(:latitude,0.0)
            set(:longitude,0.0)
            set(:plot_area,0.0)
            set(:build, 0.0)
            set(:fsi,0.0)
            set(:boundary_north,0.0)
            set(:boundary_south,0.0)
            set(:boundary_east,0.0)
            set(:boundary_west,0.0)
            set(:locationClassification,"")
            set(:zone,"")
            set(:fsi_mode,"")
            set(:setback_limit, 0.0)
            set(:overlays, [])

        end
 

        def get(key)
            @data_store[key]
        end

        def set(key,value)
            @data_store[key] = value
        end
        
        def getFSILimit            
            config_path = File.join(__dir__, '..', 'config', 'fsi-config.json')
            config = JSON.parse(File.read(config_path))

            key_location = DataPoints.get(:locationClassification)
            key_zone = DataPoints.get(:zone)
            fsi_limit = HashUtils.safe_dig(config,key_location, key_zone)            
            DataPoints.set(:fsi_limit, fsi_limit)
            return unless fsi_limit        
        end

        def getSetbackLimit
            # Load setback config
            #config_path = File.join(__dir__, '..', 'config', ProjectConstants::SETBACK_CONFIG_FILE)
            config_path = File.join(__dir__, '..', 'config', 'setback-config.json')
            config = JSON.parse(File.read(config_path))
            
            key_location = DataPoints.get(:locationClassification)
            key_zone = DataPoints.get(:zone)
            
            setbacks = HashUtils.safe_dig(config,key_location, key_zone)
            DataPoints.set(:setback_limit, setbacks)
            return unless setbacks
        end

       
        def convert_to_sq_meter(value_to_convert,model) 
            options= model.options["UnitsOptions"]
            unit = options["LengthUnit"]
            val = 0.0
            puts "unit: #{unit}"
            case unit
            when 0 # inches
                val = value_to_convert * 0.00064516
            when 1 # feet
                val = value_to_convert * 0.092903
            when 2 # Millimeters
                val = value_to_convert / 1_000_000.0
            when 3 # centimeters
                val = value_to_convert  / 10_000.0
            when 4 # meters
                val = value_to_convert
            else
               val =  value_to_convert * 0.00064516 # default to inches 
            end 
            puts "after conversion in convert  method : #{val}"
            val
        end
 
        def self.calculate_far
            set(:fsi,"N/A") # default current FSI to NA
            site_area_m2  = plot_area_from_lowest_faces
            return if  site_area_m2.nil? || site_area_m2.to_f <= 0 
            
            building_area = total_floor_area(Sketchup.active_model.entities)
            puts "in calculate _Far .....#{site_area_m2} & #{building_area}"
            far = building_area.to_i / site_area_m2.to_i
            
            puts "📐 Recalculated FAR:"
            puts "  - Site area     : #{site_area_m2.round(2)} m²"
            puts "  - Floor area    : #{building_area.round(2)} m²"
            puts "  - FAR           : #{far.round(2)}"
            set(:fsi,far.round(2))
            set(:plot_area,site_area_m2.round(2))
            set(:build,building_area.round(2))
            
            far
        end

        def self.ensure_material
            materials = Sketchup.active_model.materials
            mat = materials[MESSAGE_HEIGHT_EXCEED]
            unless mat
                mat = materials.add(MESSAGE_HEIGHT_EXCEED)
                mat.color = 'red'
            end
            mat
        end

    end
end

 