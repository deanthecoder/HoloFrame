extends SceneTree
## Verify the in-game screenshot key with a rendered frame, without writing to Downloads.

func _initialize() -> void:
	call_deferred("_check")


func _check() -> void:
	OS.set_environment("HOLOFRAME_SCREENSHOT_DIR", ProjectSettings.globalize_path("user://"))
	var scene = load("res://main.tscn").instantiate()
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
	OS.set_environment("HOLOFRAME_SCREENSHOT_DIR", "")
	print("SCREENSHOT_CHECK: S saved a unique rendered PNG")
	quit()
