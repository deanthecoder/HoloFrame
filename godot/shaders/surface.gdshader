shader_type spatial;

uniform vec4 surface_color : source_color = vec4(1.0);
uniform float surface_roughness : hint_range(0.0, 1.0) = 0.5;
uniform sampler2D webcam_image : source_color, filter_linear;
uniform vec3 webcam_position = vec3(0.0, 0.0982, 0.0);
uniform vec2 webcam_focal_uv = vec2(1.0, 1.333333);
uniform float webcam_plane_z = 0.6;

varying vec3 world_position;

void vertex() {
	world_position = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

void fragment() {
	// Keep Godot's PBR lighting, then add the limited view outside the screen.
	ALBEDO = surface_color.rgb;
	ROUGHNESS = surface_roughness;
	METALLIC = 0.0;
	SPECULAR = 0.5;

	vec3 world_normal = normalize((INV_VIEW_MATRIX * vec4(NORMAL, 0.0)).xyz);
	vec3 world_view = normalize((INV_VIEW_MATRIX * vec4(VIEW, 0.0)).xyz);
	vec3 reflected = reflect(-world_view, world_normal);
	// Reflect into the viewer's plane, then project through the top-bezel webcam.
	float ray_distance = (webcam_plane_z - world_position.z) / max(reflected.z, 0.001);
	vec3 webcam_ray = world_position + reflected * ray_distance - webcam_position;
	vec2 uv = vec2(0.5) + webcam_ray.xy / max(webcam_ray.z, 0.001)
		* webcam_focal_uv * vec2(1.0, -1.0);
	float edge = min(min(uv.x, 1.0 - uv.x), min(uv.y, 1.0 - uv.y));
	float coverage = smoothstep(0.0, 0.12, edge) * step(0.0, reflected.z) * step(0.0, ray_distance);
	float facing = clamp(dot(world_normal, world_view), 0.0, 1.0);
	float fresnel = 0.04 + 0.96 * pow(1.0 - facing, 5.0);
	float gloss = pow(1.0 - surface_roughness, 2.0);
	EMISSION = texture(webcam_image, uv).rgb * coverage * fresnel * gloss * 12.0;
}
