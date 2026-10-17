extends Node3D
## Shared tracked projection, camera reflection, calibration, and capture.

const POSE_PORT := 55123
const IMAGE_PORT := 55124
const POSE_SMOOTHING_SECONDS := 0.12
const CALIBRATION_PATH := "user://calibration.cfg"

var eye_mm := Vector3(0.0, 0.0, 600.0)
var target_eye_mm := Vector3(0.0, 0.0, 600.0)
var eye_offset_mm := Vector3.ZERO
var screen_width_m := 0.3024
var calibration_notice: Label
var notice_seconds := 0.0
var screenshot_pending := false
var camera: Camera3D
var pose_socket := PacketPeerUDP.new()
var image_socket := PacketPeerUDP.new()
var webcam_texture: ImageTexture
var webcam_position_mm := Vector3.ZERO
var webcam_focal_uv := Vector2(1.0, 4.0 / 3.0)
var surface_shader: Shader
var webcam_materials: Array[ShaderMaterial] = []


func _ready() -> void:
	_load_display_profile()
	_build_environment()
	_build_content()
	camera = Camera3D.new()
	camera.name = "TrackedCamera"
	camera.keep_aspect = Camera3D.KEEP_WIDTH
	add_child(camera)
	camera.current = true
	_load_calibration()
	_build_calibration_notice()
	_apply_projection()
	var error := pose_socket.bind(POSE_PORT, "127.0.0.1")
	if error != OK:
		push_error("Could not receive head pose on UDP port %d" % POSE_PORT)
	error = image_socket.bind(IMAGE_PORT, "127.0.0.1")
	if error != OK:
		push_error("Could not receive webcam image on UDP port %d" % IMAGE_PORT)
	_set_capture_if_requested()


func _process(delta: float) -> void:
	# Use the newest pose and smooth small tracking jumps in the displayed view.
	notice_seconds = maxf(0.0, notice_seconds - delta)
	calibration_notice.visible = notice_seconds > 0.0
	while pose_socket.get_available_packet_count() > 0:
		var packet := pose_socket.get_packet().get_string_from_utf8()
		var pose = JSON.parse_string(packet)
		if pose is Dictionary:
			var eye: Array = pose["eye_mm"]
			var webcam: Array = pose["webcam_position_mm"]
			var focal: Array = pose["focal_uv"]
			target_eye_mm = Vector3(float(eye[0]), float(eye[1]), float(eye[2]))
			webcam_position_mm = Vector3(float(webcam[0]), float(webcam[1]), float(webcam[2]))
			webcam_focal_uv = Vector2(float(focal[0]), float(focal[1]))
	while image_socket.get_available_packet_count() > 0:
		var image := Image.new()
		if image.load_jpg_from_buffer(image_socket.get_packet()) == OK:
			image.flip_x()
			webcam_texture = ImageTexture.create_from_image(image)
			for material in webcam_materials:
				material.set_shader_parameter("webcam_image", webcam_texture)
	var blend := 1.0 - exp(-delta / POSE_SMOOTHING_SECONDS)
	eye_mm = eye_mm.lerp(target_eye_mm, blend)
	_apply_projection()


func _unhandled_key_input(event: InputEvent) -> void:
	# Calibrate, capture the current view, or close the full-screen window.
	if not event is InputEventKey or not event.pressed or event.echo:
		return
	if event.keycode == KEY_ESCAPE:
		get_tree().quit()
	elif event.keycode == KEY_S:
		_take_screenshot()
	elif _handle_view_key(event):
		pass
	elif event.keycode == KEY_C:
		eye_offset_mm = Vector3.ZERO if event.shift_pressed else Vector3(-target_eye_mm.x, -target_eye_mm.y, 0.0)
		var settings := ConfigFile.new()
		settings.set_value("view", "eye_offset_mm", eye_offset_mm)
		settings.set_value("view", "reference_eye_mm", target_eye_mm)
		settings.set_value("view", "webcam_position_mm", webcam_position_mm)
		var error := settings.save(_calibration_path())
		if error != OK:
			push_error("Could not save view calibration: %d" % error)
		calibration_notice.text = "Measured view restored" if event.shift_pressed else "View centered — Shift+C to reset"
		notice_seconds = 4.0
		eye_mm = target_eye_mm
		_apply_projection()


func _take_screenshot() -> void:
	if screenshot_pending:
		return
	var downloads_dir := _screenshot_dir()
	if downloads_dir.is_empty():
		push_error("Could not find the Downloads folder")
		return
	var error := DirAccess.make_dir_recursive_absolute(downloads_dir)
	if error != OK:
		push_error("Could not create the Downloads folder: %d" % error)
		return
	screenshot_pending = true
	var path := _next_screenshot_path(downloads_dir)
	notice_seconds = 0.0
	calibration_notice.hide()
	await RenderingServer.frame_post_draw
	error = get_viewport().get_texture().get_image().save_png(path)
	screenshot_pending = false
	if error == OK:
		print("HOLOFRAME_SCREENSHOT: ", path)
		calibration_notice.text = "Screenshot saved to Downloads: " + path.get_file()
	else:
		push_error("Could not save screenshot to %s: %d" % [path, error])
		calibration_notice.text = "Could not save screenshot"
	notice_seconds = 4.0


func _next_screenshot_path(downloads_dir: String) -> String:
	var base_path := downloads_dir.path_join("HoloFrame-" + Time.get_datetime_string_from_system().replace("T", "_").replace(":", "-"))
	var path := base_path + ".png"
	var suffix := 2
	while FileAccess.file_exists(path):
		path = "%s-%d.png" % [base_path, suffix]
		suffix += 1
	return path


func _load_calibration() -> void:
	# Keep the seating adjustment between runs without changing tracked distance.
	var settings := ConfigFile.new()
	if settings.load(_calibration_path()) == OK:
		eye_offset_mm = settings.get_value("view", "eye_offset_mm", Vector3.ZERO)
		eye_mm = settings.get_value("view", "reference_eye_mm", Vector3(-eye_offset_mm.x, -eye_offset_mm.y, 600.0))
		# Preserve the seated view when correcting the tracker's camera origin.
		var old_origin: Vector3 = settings.get_value("view", "webcam_position_mm", Vector3(0, 115.5, 0))
		var origin_change := webcam_position_mm - old_origin
		eye_mm += origin_change
		if not eye_offset_mm.is_zero_approx():
			eye_offset_mm -= origin_change
		target_eye_mm = eye_mm


func _load_display_profile() -> void:
	# Both processes use one measured display profile, independent of room size.
	var profile: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://display_profile.json"))
	screen_width_m = float(profile["screen_width_mm"]) * 0.001
	webcam_position_mm = Vector3(0.0, float(profile["screen_height_mm"]) * 0.5 + float(profile["webcam_above_screen_mm"]), 0.0)


func _build_calibration_notice() -> void:
	# Show the shortcut briefly so the scene stays clear during normal use.
	var overlay := CanvasLayer.new()
	add_child(overlay)
	calibration_notice = Label.new()
	calibration_notice.text = "Sit comfortably, then press C to center the view · Shift+C resets"
	calibration_notice.position = Vector2(20, 20)
	calibration_notice.add_theme_color_override("font_shadow_color", Color.BLACK)
	calibration_notice.add_theme_constant_override("shadow_offset_x", 1)
	calibration_notice.add_theme_constant_override("shadow_offset_y", 1)
	overlay.add_child(calibration_notice)
	notice_seconds = 6.0


func _apply_projection() -> void:
	# The near-plane aperture is the measured screen scaled by eye distance.
	var eye := (eye_mm + eye_offset_mm) * 0.001
	var distance: float = maxf(eye.z, 0.05)
	var near := 0.02
	camera.position = eye
	camera.set_frustum(screen_width_m * near / distance,
		Vector2(-eye.x, -eye.y) * near / distance, near, 5.0)
	# Reproject the webcam at the viewer's depth in the same calibrated space.
	for material in webcam_materials:
		material.set_shader_parameter("webcam_position", (webcam_position_mm + eye_offset_mm) * 0.001)
		material.set_shader_parameter("webcam_focal_uv", webcam_focal_uv)
		material.set_shader_parameter("webcam_plane_z", eye.z)


func _material(color: Color, roughness: float) -> ShaderMaterial:
	# Every opaque surface keeps dielectric specular response; roughness varies by material.
	var material := ShaderMaterial.new()
	material.shader = surface_shader
	material.set_shader_parameter("surface_color", color)
	material.set_shader_parameter("surface_roughness", roughness)
	material.set_shader_parameter("webcam_image", webcam_texture)
	webcam_materials.append(material)
	return material


func _build_environment() -> void:
	# A neutral sky gives every material a broad reflection.
	var neutral_image := Image.create(128, 72, false, Image.FORMAT_RGB8)
	neutral_image.fill(Color(0.2, 0.2, 0.2))
	webcam_texture = ImageTexture.create_from_image(neutral_image)
	surface_shader = load("res://shaders/surface.gdshader")
	var sky_material := ProceduralSkyMaterial.new()
	sky_material.sky_top_color = Color(0.32, 0.38, 0.48)
	sky_material.sky_horizon_color = Color(0.70, 0.68, 0.64)
	sky_material.ground_bottom_color = Color(0.18, 0.18, 0.18)
	var sky := Sky.new()
	sky.sky_material = sky_material
	var environment := Environment.new()
	environment.background_mode = Environment.BG_SKY
	environment.sky = sky
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = Color(0.65, 0.66, 0.68)
	environment.reflected_light_source = Environment.REFLECTION_SOURCE_BG
	environment.ambient_light_energy = 0.1
	environment.ssao_enabled = true
	environment.ssao_radius = 0.04
	environment.ssao_intensity = 0.9
	environment.ssil_enabled = true
	environment.ssil_radius = 0.15
	environment.ssil_intensity = 1.0
	environment.ssr_enabled = true
	# Give bright emitters and highlights a small halo without washing out the room.
	environment.glow_enabled = true
	environment.glow_blend_mode = Environment.GLOW_BLEND_MODE_ADDITIVE
	environment.glow_intensity = 0.12
	environment.glow_hdr_threshold = 1.1
	environment.glow_bloom = 0.0
	var world := WorldEnvironment.new()
	world.name = "WorldEnvironment"
	world.environment = environment
	add_child(world)


func _set_capture_if_requested() -> void:
	# Save a rendered frame for visual comparison when run with --capture PATH.
	var args := OS.get_cmdline_user_args()
	var index := args.find("--capture")
	if index < 0 or index + 1 >= args.size():
		return
	_capture_after_delay(args[index + 1])


func _capture_after_delay(path: String) -> void:
	notice_seconds = 0.0
	calibration_notice.hide()
	# Wait for imported meshes, sky, and shadows to finish their first frames.
	await get_tree().create_timer(2.0).timeout
	await RenderingServer.frame_post_draw
	var image := get_viewport().get_texture().get_image()
	var error := image.save_png(path)
	print("HOLOFRAME_CAPTURE: ", path, " error=", error,
		" fps=", Engine.get_frames_per_second())
	get_tree().quit()


func _build_content() -> void:
	pass


func _handle_view_key(_event: InputEventKey) -> bool:
	return false


func _calibration_path() -> String:
	var override := OS.get_environment("HOLOFRAME_CALIBRATION_PATH")
	return override if not override.is_empty() else CALIBRATION_PATH


func _screenshot_dir() -> String:
	var override := OS.get_environment("HOLOFRAME_SCREENSHOT_DIR")
	return override if not override.is_empty() else OS.get_system_dir(OS.SYSTEM_DIR_DOWNLOADS)
