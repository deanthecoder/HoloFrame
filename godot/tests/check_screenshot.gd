extends SceneTree
## Verify the in-game screenshot key with a rendered frame, without writing to Downloads.

func _initialize() -> void:
	call_deferred("_check")


func _check() -> void:
	var script := GDScript.new()
	script.source_code = FileAccess.get_file_as_string("res://scripts/main.gd") \
		.replace("OS.get_system_dir(OS.SYSTEM_DIR_DOWNLOADS)", "ProjectSettings.globalize_path(\"user://\")")
	assert(script.reload() == OK)
	var scene = load("res://main.tscn").instantiate()
	scene.set_script(script)
	root.add_child(scene)
	var key := InputEventKey.new()
	key.keycode = KEY_S
	key.pressed = true
	scene._unhandled_key_input(key)
	assert(scene.screenshot_pending)
	await RenderingServer.frame_post_draw
	await process_frame
	assert(not scene.screenshot_pending)
	var test_dir := ProjectSettings.globalize_path("user://")
	var screenshot_path: String = test_dir.path_join(scene.calibration_notice.text.trim_prefix("Screenshot saved to Downloads: "))
	assert(FileAccess.file_exists(screenshot_path))
	var screenshot := Image.new()
	assert(screenshot.load(screenshot_path) == OK)
	assert(screenshot.get_size() == root.size)
	assert(scene._next_screenshot_path(test_dir) != screenshot_path)
	DirAccess.remove_absolute(screenshot_path)
	print("SCREENSHOT_CHECK: S saved a unique rendered PNG")
	quit()
