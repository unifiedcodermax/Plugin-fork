require_relative '../config/constants'
require_relative '../helpers/datapoints'
require_relative '../helpers/hash_utils'

module SV_Abid
    module SetBack
        extend self

        def check_setback_compliance
            model = Sketchup.active_model
            entities = model.entities
            plot_face = Sketchup.active_model.active_entities
            return unless plot_face

            plot_bounds = plot_face.bounds
            plot_edges = plot_face.edges.map(&:line)

            # Load setback config
            #config_path = File.join(__dir__, '..', 'config', ProjectConstants::SETBACK_CONFIG_FILE)
            config_path = File.join(__dir__, '..', 'config', 'setback-config.json')
            config = JSON.parse(File.read(config_path))
            
            key_location = DataPoints.get(:locationClassification)
            key_zone = DataPoints.get(:zone)
            
            setbacks = HashUtils.safe_dig(config,key_location, key_zone)
            
            return unless setbacks

            violations = []

            # Check all groups/components for distance from plot edges
            entities.grep(Sketchup::Group).each do |group|
                group.bounds.corner(0..7).each do |corner|
                    distance = closest_edge_distance(corner, plot_edges)
                    if distance < setbacks.values.min.m
                        violations << group
                        break
                    end
                end
            end

            if violations.any?
                UI.messagebox("🚧 Setback Violation Detected: #{violations.size} object(s) too close to boundary.")
            end
        end

        # Helper to find shortest distance from point to any line
        def closest_edge_distance(point, edges)
            min_dist = Float::INFINITY
            edges.each do |line|
                dist = point_to_line_distance(point, line)
                min_dist = dist if dist < min_dist
            end
            min_dist
        end

        # Geometry utility
        def point_to_line_distance(pt, line)
            origin, direction = line
            vec = pt.vector_to(origin)
            proj = vec.project_to_plane(direction)
            proj.length
        end

        def get_setback_compliance
            puts "in get setback...."
            faces = DataPoints.get_all_faces(Sketchup.active_model.entities) 
            setbacks = DataPoints.get(:setback_limit) 
            puts faces
            faces.each do |face|
                face.vertices.each do |v|
                    pt = v.position
                    if pt.x.abs < setbacks.m || pt.y.abs < setbacks.m
                        #UI.messagebox("⚠️ Setback violation detected!\nSome part of building is within #{setbacks} m from boundary.")
                        break
                    end
                end
            end
            faces            
        end

        def get_setbackLimit
            config_path = File.join(__dir__, '..', 'config', 'setback-config.json')
            config = JSON.parse(File.read(config_path))
            
            key_location = DataPoints.get(:locationClassification)
            key_zone = DataPoints.get(:zone)
            
            setbacks = HashUtils.safe_dig(config,key_location, key_zone) 
            return unless setbacks

            DataPoints.set(:setback_limit,setbacks)
            setbacks

        end 
    end
end 