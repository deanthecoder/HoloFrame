extends "res://scripts/base_view.gd"
## Framed depth photos on a gallery wall.

var photo_views: Array[Node3D] = []
var active_photo_index := 0
var gallery_stage: Node3D
const STAGE_Z := 0.27
const STAGE_SCALE := 0.52


func _build_environment() -> void:
	super._build_environment()
	# The room's broad SSAO halo makes a wall-mounted frame look detached.
	$WorldEnvironment.environment.ssao_enabled = false
	$WorldEnvironment.environment.ssil_enabled = false
	$WorldEnvironment.environment.ambient_light_energy = 0.24


func _build_content() -> void:
	gallery_stage = Node3D.new()
	gallery_stage.name = "GalleryStage"
	# The wall lies on the physical screen plane. The frame and relief project
	# a few centimetres toward the viewer, so approaching makes them grow.
	gallery_stage.position.z = STAGE_Z
	gallery_stage.scale = Vector3(STAGE_SCALE, STAGE_SCALE, 1.0)
	add_child(gallery_stage)
	_build_gallery_wall()
	_load_photo_views()


func _handle_view_key(event: InputEventKey) -> bool:
	if event.keycode >= KEY_1 and event.keycode <= KEY_3:
		_show_photo(event.keycode - KEY_1)
		return true
	return false


func _build_gallery_wall() -> void:
	# A shallow wall leaves space for the frame to cast a real shadow.
	var wall := MeshInstance3D.new()
	wall.name = "GalleryWall"
	var wall_mesh := BoxMesh.new()
	wall_mesh.size = Vector3(2.0, 1.4, 0.03)
	wall.mesh = wall_mesh
	wall.position.z = -0.285
	var wall_image := Image.create(256, 256, false, Image.FORMAT_RGB8)
	var normal_image := Image.create(256, 256, false, Image.FORMAT_RGB8)
	var plaster := FastNoiseLite.new()
	plaster.seed = 47
	plaster.frequency = 0.08
	var grain := FastNoiseLite.new()
	grain.seed = 81
	grain.frequency = 0.68
	for y in range(256):
		for x in range(256):
			var coarse := plaster.get_noise_2d(x, y)
			var fine := grain.get_noise_2d(x, y)
			var shade := 0.83 + coarse * 0.065 + fine * 0.035
			wall_image.set_pixel(x, y, Color(shade, shade * 0.995, shade * 0.985))
			var dx := grain.get_noise_2d(x + 1, y) - grain.get_noise_2d(x - 1, y)
			var dy := grain.get_noise_2d(x, y + 1) - grain.get_noise_2d(x, y - 1)
			var normal := Vector3(-dx * 0.09, -dy * 0.09, 1.0).normalized()
			normal_image.set_pixel(x, y, Color(normal.x * 0.5 + 0.5, normal.y * 0.5 + 0.5, normal.z * 0.5 + 0.5))
	wall_image.generate_mipmaps()
	normal_image.generate_mipmaps()
	var wall_material := StandardMaterial3D.new()
	wall_material.albedo_texture = ImageTexture.create_from_image(wall_image)
	wall_material.uv1_scale = Vector3(4.0, 4.0, 1.0)
	wall_material.normal_enabled = true
	wall_material.normal_texture = ImageTexture.create_from_image(normal_image)
	wall_material.roughness = 0.84
	wall_material.metallic_specular = 0.35
	wall.material_override = wall_material
	gallery_stage.add_child(wall)
	for side in [-1, 1]:
		var light := OmniLight3D.new()
		light.name = "PictureLightLeft" if side < 0 else "PictureLightRight"
		light.position = Vector3(side * 0.11, 0.07, -0.02)
		gallery_stage.add_child(light)
		light.light_color = Color(1.0, 0.94, 0.84)
		light.light_energy = 0.16
		light.light_size = 0.08
		light.omni_range = 1.5
		light.shadow_enabled = true
		light.shadow_bias = 0.008


func _add_frame(view: Node3D, width: float, height: float) -> void:
	var wood := _frame_material(Color(0.09, 0.055, 0.034), 0.54, 0.0)
	var brass := _frame_material(Color(0.38, 0.27, 0.11), 0.46, 0.55)
	var mat := _frame_material(Color(0.78, 0.74, 0.67), 0.82, 0.0)
	# The mat and photo sit behind a single bevelled, 16.5 mm deep ring.
	var photo_mat := _add_box(view, "PhotoMat", Vector3(width + 0.012, height + 0.012, 0.006), Vector3(0, 0, -0.259), mat)
	photo_mat.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var frame := MeshInstance3D.new()
	frame.name = "BevelledFrame"
	frame.mesh = _frame_mesh(width, height)
	frame.material_override = wood
	view.add_child(frame)
	var liner := MeshInstance3D.new()
	liner.name = "BrassLiner"
	liner.mesh = _ring_mesh(width * 0.5 + 0.005, height * 0.5 + 0.005,
		width * 0.5 + 0.002, height * 0.5 + 0.002, -0.2455)
	liner.material_override = brass
	liner.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	view.add_child(liner)


func _frame_material(color: Color, roughness: float, metallic: float) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.roughness = roughness
	material.metallic = metallic
	return material


func _frame_mesh(width: float, height: float) -> ArrayMesh:
	var half_w := width * 0.5
	var half_h := height * 0.5
	var rings := [
		Vector3(half_w + 0.024, half_h + 0.024, -0.264),
		Vector3(half_w + 0.024, half_h + 0.024, -0.251),
		Vector3(half_w + 0.020, half_h + 0.020, -0.2475),
		Vector3(half_w + 0.002, half_h + 0.002, -0.2475),
		Vector3(half_w + 0.002, half_h + 0.002, -0.258),
	]
	var surface := SurfaceTool.new()
	surface.begin(Mesh.PRIMITIVE_TRIANGLES)
	for ring_index in range(rings.size() - 1):
		_append_ring_strip(surface, rings[ring_index], rings[ring_index + 1])
	surface.generate_normals()
	return surface.commit()


func _ring_mesh(outer_w: float, outer_h: float, inner_w: float, inner_h: float, z: float) -> ArrayMesh:
	var surface := SurfaceTool.new()
	surface.begin(Mesh.PRIMITIVE_TRIANGLES)
	_append_ring_strip(surface, Vector3(outer_w, outer_h, z), Vector3(inner_w, inner_h, z))
	surface.generate_normals()
	return surface.commit()


func _append_ring_strip(surface: SurfaceTool, outer: Vector3, inner: Vector3) -> void:
	var signs := [Vector2(-1, 1), Vector2(1, 1), Vector2(1, -1), Vector2(-1, -1)]
	for i in range(4):
		var j := (i + 1) % 4
		var a := Vector3(signs[i].x * outer.x, signs[i].y * outer.y, outer.z)
		var b := Vector3(signs[j].x * outer.x, signs[j].y * outer.y, outer.z)
		var c := Vector3(signs[j].x * inner.x, signs[j].y * inner.y, inner.z)
		var d := Vector3(signs[i].x * inner.x, signs[i].y * inner.y, inner.z)
		for vertex in [a, b, c, a, c, d]:
			surface.add_vertex(vertex)


func _add_box(parent: Node3D, name: String, size: Vector3, position: Vector3, material: Material) -> MeshInstance3D:
	var part := MeshInstance3D.new()
	part.name = name
	var mesh := BoxMesh.new()
	mesh.size = size
	part.mesh = mesh
	part.position = position
	part.material_override = material
	parent.add_child(part)
	return part


func _load_photo_views() -> void:
	var args := OS.get_cmdline_user_args()
	var cursor := 0
	while cursor < args.size():
		if args[cursor] != "--photo":
			cursor += 1
			continue
		if cursor + 7 >= args.size() or args[cursor + 2] != "--depth" or args[cursor + 4] != "--background" or args[cursor + 6] != "--foreground":
			push_error("Each photo needs --photo PATH --depth PATH --background PATH --foreground PATH")
			return
		var view := _build_photo(args[cursor + 1], args[cursor + 3], args[cursor + 5], args[cursor + 7])
		if view == null:
			return
		view.name = "Photo%d" % (photo_views.size() + 1)
		view.visible = photo_views.is_empty()
		gallery_stage.add_child(view)
		photo_views.append(view)
		cursor += 8


func _show_photo(index: int) -> void:
	if index >= photo_views.size():
		return
	active_photo_index = index
	for i in range(photo_views.size()):
		photo_views[i].visible = i == index
	calibration_notice.text = "Photo %d of %d" % [index + 1, photo_views.size()]
	notice_seconds = 2.0


func _build_photo(photo_path: String, depth_path: String, background_path: String, foreground_path: String) -> Node3D:
	var photo := Image.new()
	var depth := Image.new()
	var background := Image.new()
	var foreground := Image.new()
	if photo.load(photo_path) != OK or depth.load(depth_path) != OK or background.load(background_path) != OK or foreground.load(foreground_path) != OK:
		push_error("Could not load the photo or its prepared layers")
		return null
	var view := Node3D.new()
	depth.convert(Image.FORMAT_L8)
	var texture := ImageTexture.create_from_image(photo)
	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.cull_mode = BaseMaterial3D.CULL_DISABLED
	material.albedo_texture = texture
	material.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS
	var aspect := float(photo.get_width()) / float(photo.get_height())
	var height := minf(0.24, 0.30 / aspect)
	var width := height * aspect
	# A flat copy provides a first background where depth edges open up.
	var backing := MeshInstance3D.new()
	backing.name = "PhotoBacking"
	var plane := QuadMesh.new()
	plane.size = Vector2(width, height)
	backing.mesh = plane
	backing.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var background_material := material.duplicate() as StandardMaterial3D
	background_material.albedo_texture = ImageTexture.create_from_image(background)
	backing.material_override = background_material
	backing.position.z = -0.255
	view.add_child(backing)

	var vertices := PackedVector3Array()
	var uvs := PackedVector2Array()
	var indices := PackedInt32Array()
	var alphas := PackedFloat32Array()
	var cols := depth.get_width()
	var rows := depth.get_height()
	for y in range(rows):
		for x in range(cols):
			var uv := Vector2(float(x) / float(cols - 1), float(y) / float(rows - 1))
			var value := depth.get_pixel(x, y).r
			# Keep the relief mostly inside the frame; its nearest points protrude
			# only a couple of centimetres beyond the front lip.
			var z := lerpf(-0.253, -0.2375, value)
			# Match the original image at the reference eye; movement reveals parallax.
			var perspective_scale := (0.6 - (z + STAGE_Z)) / (0.6 - (-0.255 + STAGE_Z))
			vertices.append(Vector3((uv.x - 0.5) * width * perspective_scale,
				(0.5 - uv.y) * height * perspective_scale, z))
			uvs.append(uv)
			var color_x := mini(int(uv.x * foreground.get_width()), foreground.get_width() - 1)
			var color_y := mini(int(uv.y * foreground.get_height()), foreground.get_height() - 1)
			alphas.append(foreground.get_pixel(color_x, color_y).a)
	for y in range(rows - 1):
		for x in range(cols - 1):
			var a := y * cols + x
			var b := a + 1
			var c := a + cols
			var d := c + 1
			# Keep triangles wholly inside the cutout. A depth edge joined to the
			# unseen background otherwise folds into long slivers at side angles.
			if minf(alphas[a], minf(alphas[c], alphas[b])) >= 0.5:
				indices.append_array(PackedInt32Array([a, c, b]))
			if minf(alphas[b], minf(alphas[c], alphas[d])) >= 0.5:
				indices.append_array(PackedInt32Array([b, c, d]))
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = vertices
	arrays[Mesh.ARRAY_TEX_UV] = uvs
	arrays[Mesh.ARRAY_INDEX] = indices
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	var relief := MeshInstance3D.new()
	relief.name = "PhotoRelief"
	relief.mesh = mesh
	relief.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var foreground_material := material.duplicate() as StandardMaterial3D
	foreground_material.albedo_texture = ImageTexture.create_from_image(foreground)
	# Alpha blending sorts this whole mesh as one object; cutout fragments
	# write depth so nearer parts occlude farther parts as the eye moves.
	foreground_material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR
	foreground_material.alpha_scissor_threshold = 0.5
	foreground_material.cull_mode = BaseMaterial3D.CULL_DISABLED
	relief.material_override = foreground_material
	view.add_child(relief)
	_add_frame(view, width, height)
	return view
