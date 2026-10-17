extends SceneTree
## Regression checks for saved seating calibration and startup without a face.

func _initialize() -> void:
	call_deferred("_check")


func _check() -> void:
	# Use a separate settings file so verification never changes the user's seat.
	OS.set_environment("HOLOFRAME_CALIBRATION_PATH", "user://calibration-check.cfg")
	var scene = load("res://main.tscn").instantiate()
	root.add_child(scene)
	assert(is_equal_approx(scene.screen_width_m, 0.3024))
	# Screen corners must stay fixed under lateral, vertical, and depth movement.
	var aspect := float(root.size.x) / root.size.y
	for eye in [Vector3(0, 0, 600), Vector3(70, 40, 450), Vector3(-60, -30, 800)]:
		scene.eye_mm = eye
		scene.eye_offset_mm = Vector3.ZERO
		scene._apply_projection()
		scene.camera.force_update_transform()
		var projection := Projection.create_frustum_aspect(scene.camera.size, aspect, scene.camera.frustum_offset, scene.camera.near, scene.camera.far, true)
		for corner in [Vector2(-1, -1), Vector2(1, -1), Vector2(-1, 1), Vector2(1, 1)]:
			var point := Vector3(corner.x * 0.3024 / 2, corner.y * 0.3024 / aspect / 2, 0)
			var local: Vector3 = scene.camera.global_transform.affine_inverse() * point
			var clip := projection * Vector4(local.x, local.y, local.z, 1)
			assert(Vector2(clip.x / clip.w, clip.y / clip.w).distance_to(corner) < 0.001)
	scene.target_eye_mm = Vector3(35, 140, 650)
	var key := InputEventKey.new()
	key.keycode = KEY_C
	key.pressed = true
	scene._unhandled_key_input(key)
	assert(scene.eye_offset_mm == Vector3(-35, -140, 0))
	scene.eye_mm = Vector3(0, 0, 600)
	scene.target_eye_mm = scene.eye_mm
	scene._load_calibration()
	scene._process(1.0 / 60.0)
	assert(scene.eye_mm == Vector3(35, 140, 650))
	assert(scene.target_eye_mm == scene.eye_mm)
	assert(scene.camera.position.is_equal_approx(Vector3(0, 0, 0.65)))
	var sender := PacketPeerUDP.new()
	sender.set_dest_address("127.0.0.1", 55123)
	var pose := {"eye_mm": [25, 130, 640], "webcam_position_mm": [0, 115.5, 0], "focal_uv": [1, 4.0 / 3.0]}
	assert(sender.put_packet(JSON.stringify(pose).to_utf8_buffer()) == OK)
	await create_timer(0.1).timeout
	scene._process(1.0 / 60.0)
	assert(scene.target_eye_mm == Vector3(25, 130, 640))
	assert(scene.webcam_focal_uv.is_equal_approx(Vector2(1, 4.0 / 3.0)))
	assert(scene.webcam_materials[0].get_shader_parameter("webcam_position").is_equal_approx(Vector3(-0.035, -0.0245, 0)))
	sender.close()
	# Older calibrations saved only an offset; they must also start centered.
	var legacy := ConfigFile.new()
	legacy.set_value("view", "eye_offset_mm", Vector3(-35, -140, 0))
	assert(legacy.save("user://calibration-check.cfg") == OK)
	scene._load_calibration()
	scene._process(1.0 / 60.0)
	assert(scene.camera.position.is_equal_approx(Vector3(0, 0, 0.6)))
	scene.webcam_position_mm = Vector3(0, 98.2, 0)
	scene._load_calibration()
	scene._process(1.0 / 60.0)
	assert(scene.camera.position.is_equal_approx(Vector3(0, 0, 0.6)))
	assert(scene.eye_offset_mm.is_equal_approx(Vector3(-35, -122.7, 0)))
	key.shift_pressed = true
	scene._unhandled_key_input(key)
	assert(scene.eye_offset_mm == Vector3.ZERO)
	for name in ["Floor", "Ceiling", "LeftWall", "RightWall", "BackWall", "TallBlock", "ShortBlock", "Sphere"]:
		assert(scene.get_node("Room/" + name).cast_shadow == GeometryInstance3D.SHADOW_CASTING_SETTING_ON)
	assert(scene.get_node("Teapot").cast_shadow == GeometryInstance3D.SHADOW_CASTING_SETTING_ON)
	DirAccess.remove_absolute("user://calibration-check.cfg")
	OS.set_environment("HOLOFRAME_CALIBRATION_PATH", "")
	print("VIEW_CHECK: saved/legacy startup, display calibration migration, pose metadata, reflection uniforms, reset, and shadows passed")
	quit()
