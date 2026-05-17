require_relative '../core/abid_fsi'

module SV_Abid
    module Calculations
        def self.update_calculations(model)  
            #model = Sketchup.active_model
            return unless model
            puts "calling calculations for floorarea, plotarea, heights...."
            calculate_heights(model)
            FSILogic.check_fsi_compliance 
        end 
        
        def self.calculate_heights(model) 
            puts "in calculate heights....."             
            self.calculate_model_height(model)                                 
        end

        def self.calculate_model_height(model)
             # === Calculate Model Height ===
            puts "in calculate model height..."
            plot_area_m2 = DataPoints.get(:plot_area)
            bounds = Geom::BoundingBox.new
            model.entities.each do |entity|
                next unless entity.respond_to?(:bounds)
                next if entity.hidden?
                next if entity.respond_to?(:locked?) && entity.locked?
                bounds.add(entity.bounds)
            end 
            model_height_in = (bounds.max.z - bounds.min.z) # inches 
            model_height_m = model_height_in / 39.3701

            
            default_floor_height_in = 3 * 39.3701 # default height of each floor is 3 meters
            # === Estimate floor count from height if none found ===
            estimated_floor_count = (model_height_in / default_floor_height_in).ceil

            # Estimate floor area from bounding box XY size
            xy_width_m = (bounds.max.x - bounds.min.x) / 39.3701
            xy_depth_m = (bounds.max.y - bounds.min.y) / 39.3701
            estimated_floor_area = xy_width_m * xy_depth_m
            total_builtup_area = estimated_floor_area * estimated_floor_count

            far = total_builtup_area / plot_area_m2
            puts "#{model_height_m} m - estimated floor  count - #{estimated_floor_count}"
            DataPoints.set(:height,model_height_m.round(2))
            DataPoints.set(:floors,estimated_floor_count)
            DataPoints.set(:fsi,far.round(2))
            DataPoints.set(:build,total_builtup_area.round(2))
        end

        def self.calculate_height_by_groups(model)
            # === Detect named "Floor X" components/groups ===
             puts "in calculate  height based on groups / components..."
            floor_regex = /^floor\s*\d+$/i
            floor_areas_m2 = []
            named_floor_count = 0

            entities.each do |entity|
                next unless entity.is_a?(Sketchup::Group) || entity.is_a?(Sketchup::ComponentInstance)
                next if entity.hidden?
                next if entity.respond_to?(:locked?) && entity.locked?

                name = entity.name.strip
                if name.match(floor_regex)
                    # Get horizontal face area inside the group/component
                    sub_entities = entity.is_a?(Sketchup::Group) ? entity.entities : entity.definition.entities
                    area = 0.0
                    sub_entities.grep(Sketchup::Face).each do |face|
                        normal = face.normal
                        if normal.samedirection?(Z_AXIS) || normal.samedirection?(Z_AXIS.reverse)
                            area += face.area
                        end
                    end
                    area_m2 = area / (39.3701 ** 2)
                    floor_areas_m2 << area_m2.round(2)
                    named_floor_count += 1
                end 
            end
            if named_floor_count > 0
                average_floor_area = floor_areas_m2.sum / floor_areas_m2.size
                total_builtup_area = average_floor_area * named_floor_count

                far = total_builtup_area / plot_area_m2
                DataPoints.set(:height, DataPoints.convert_to_sq_meter(floor_areas_m2.sum,model).round(2) )
                DataPoints.set(:floors,named_floor_count)
                DataPoints.set(:fsi,far.round(2))
                DataPoints.set(:build,total_builtup_area.round(2))
            end  
        end       
    end
end