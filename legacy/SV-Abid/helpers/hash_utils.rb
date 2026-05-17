module HashUtils
  def self.safe_dig(hash, *keys)
    keys.reduce(hash) { |h, key| h.is_a?(Hash) ? h[key] : nil }
  end
end



module FARCalculator
  def self.calculate_far
    model = Sketchup.active_model
    entities = model.active_entities

    # === Ask user for default floor height ===
    floor_height_input = UI.inputbox(["Enter default floor height (m):"], [3.0], "Floor Height Setting")
    return unless floor_height_input
    default_floor_height_m = floor_height_input[0].to_f
    default_floor_height_in = default_floor_height_m * 39.3701

    # === Ask user for plot area (m²) ===
    plot_area_input = UI.inputbox(["Enter Plot Area (sq.m):"], [0.0], "Plot Area Input")
    return unless plot_area_input
    plot_area_m2 = plot_area_input[0].to_f

    if plot_area_m2 <= 0
      UI.messagebox("⚠️ Plot area must be greater than 0.")
      return
    end

    # === Calculate Model Height ===
    bounds = Geom::BoundingBox.new
    entities.each do |entity|
      next unless entity.respond_to?(:bounds)
      next if entity.hidden?
      next if entity.respond_to?(:locked?) && entity.locked?
      bounds.add(entity.bounds)
    end

    model_height_in = bounds.max.z - bounds.min.z
    model_height_m = model_height_in / 39.3701

    # === Detect named "Floor X" components/groups ===
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

    # === Estimate floor count from height if none found ===
    estimated_floor_count = (model_height_in / default_floor_height_in).ceil

    # === Calculate Built-up Area ===
    if named_floor_count > 0
      average_floor_area = floor_areas_m2.sum / floor_areas_m2.size
      total_builtup_area = average_floor_area * named_floor_count
    else
      # Estimate floor area from bounding box XY size
      xy_width_m = (bounds.max.x - bounds.min.x) / 39.3701
      xy_depth_m = (bounds.max.y - bounds.min.y) / 39.3701
      estimated_floor_area = xy_width_m * xy_depth_m
      total_builtup_area = estimated_floor_area * estimated_floor_count
    end

    # === Calculate FAR ===
    far = total_builtup_area / plot_area_m2

    # === Build message for user ===
    message = "📏 Model Height: #{model_height_m.round(2)} m\n"
    message += "🧱 Default Floor Height: #{default_floor_height_m} m\n"
    message += "📐 Plot Area: #{plot_area_m2.round(2)} m²\n"
    message += "🏢 Built-up Area: #{total_builtup_area.round(2)} m²\n"
    message += "📊 Floor Area Ratio (FAR): #{far.round(2)}"

    UI.messagebox(message)
  end
end

# Run the FAR calculator
FARCalculator.calculate_far
