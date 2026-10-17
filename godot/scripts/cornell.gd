extends "res://scripts/base_view.gd"
## Original Cornell room scene.


func _build_content() -> void:
	_apply_room_materials()
	_build_objects()


func _apply_room_materials() -> void:
	# Preserve authored colors while adding the webcam reflection to each surface.
	for child in $Room.get_children():
		if child is MeshInstance3D:
			var source: StandardMaterial3D = child.material_override
			if not source.emission_enabled:
				child.material_override = _material(source.albedo_color, source.roughness)


func _build_objects() -> void:
	# Keep the teapot in front of the physical screen, as in the first prototype.
	var teapot_mesh = load("res://models/teapot.obj")
	if not teapot_mesh is Mesh:
		push_error("Could not load the teapot mesh")
		return
	var teapot := MeshInstance3D.new()
	teapot.name = "Teapot"
	teapot.mesh = teapot_mesh
	teapot.material_override = _material(Color(0.72, 0.77, 0.80), 0.22)
	var bounds: AABB = teapot_mesh.get_aabb()
	var scale_factor: float = 0.15 / maxf(bounds.size.x, maxf(bounds.size.y, bounds.size.z))
	teapot.scale = Vector3.ONE * scale_factor
	teapot.position = -bounds.get_center() * scale_factor + Vector3(0, 0, 0.1)
	add_child(teapot)
