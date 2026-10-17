# Rendering and calibration notes

HoloFrame has a Cornell room scene (`main.tscn` and `scripts/cornell.gd`) and a
framed photo gallery (`gallery.tscn` and `scripts/gallery.gd`). Both use
`scripts/base_view.gd` for tracking, projection, calibration, and capture.
In the gallery, the wall lies at the screen plane and the frame projects about
2 cm toward the viewer. This makes it grow slightly as the viewer approaches.
The room contains one teapot, two blocks, and one sphere. Godot 4.7 Forward+ renders it with PBR materials, live shadows,
TAA, subtle SSAO and SSIL, screen-space reflections, and a small HDR glow around bright
emitters and highlights. The same Python/MediaPipe
tracker captures the webcam once and sends eye position and a blurred 128 × 72
image over localhost. Godot uses the image as a partial reflected environment
on every material. Neither process saves webcam frames.

Godot adds a light 120 ms smoothing pass to the displayed head position and
mirrors the webcam image horizontally for the reflections.

Sit in your normal position and press **C** to center the view on the teapot.
This saves a horizontal and vertical eye offset between runs; distance and head
movement remain tracked. Press **Shift+C** to clear it. This comfort calibration
adjusts the estimated eye position, so use the unadjusted view when assessing
physical screen alignment. Recalibrate after moving the screen or webcam.
Startup restores the saved reference eye position, and missing face detections
hold the last valid view rather than moving toward an uncalibrated default.

## Run on this Mac

From the repository root, start both processes:

```sh
./run_godot.sh
```

On first setup, the tracker scans cameras until it detects a face, then stays on
that device through later face loss. Later runs use only that camera, even if it
temporarily produces no face detections. Run `./run_godot.sh --reset-camera` to
clear the choice and scan again. The successful device is remembered in the ignored
`.holoframe-camera.json` file; device identity is used because indices can change.
You can still force an index with `./run_godot.sh 1` or `--camera-index 1`.
Press Escape to quit and release the camera. Godot can also render without the
tracker using its saved reference eye position and a neutral reflection image.

`display_profile.json` is shared by the tracker and renderer. It is configured
for the 14-inch 2021 MacBook Pro: 302.4 mm wide, with a measured fullscreen area
of 189.8 mm high below the notch/menu strip. The native panel is 3024 × 1964 at
254 ppi (302.4 × 196.4 mm); Godot reports a 3024 × 1898 fullscreen window at
pixel position (0, 66) on this Mac. The 3.3 mm webcam offset above that window
estimates the lens at the midpoint of the excluded strip; this is not a measured
lens mount position. Update this profile for a different display or fullscreen
area.

The room remains 344 mm wide, extending beyond the physical aperture. Its props
and lights keep their authored dimensions; correcting display size changes only
the view through the screen. Existing seating calibrations compensate for the
corrected webcam origin automatically; press C to recalibrate if needed.

## Rendering choices

The room and props are fixed in `room.tscn`. Godot's LightmapGI bakes three
bounces from the emissive ceiling panel and indirect light from the lights.
A warm key under the panel and a weaker viewer-side fill cast live shadows.
The ceiling, walls, blocks, sphere, and teapot all cast shadows. The emissive
panel is excluded so it does not obstruct its own light.
`room.exr` and `room.lmbake` are the saved
bake; after changing the room or its lights, select its LightmapGI node in the
Godot editor and click **Bake Lightmaps**, then save the scene.

One box-projected ReflectionProbe captures the room, while screen-space
reflections add visible detail. The webcam image adds a broad, partial reflection
on every surface. All materials remain dielectric; the matte walls have high
roughness so they reflect light without looking glossy.

Webcam reflections start from the same approximate intrinsics as head tracking, with
the camera's height above screen center and the saved seating offset applied.
Reflected rays sample the image on a plane at the tracked eye distance. This
corrects the former height mismatch. The image is spread more broadly over curved
surfaces so its blurred details remain visible; it remains an approximation
for a room with objects at different depths. Exact alignment requires measured
webcam intrinsics and its position relative to the screen. The original capture's
aspect ratio is sent with the pose, so resizing the stream does not alter the mapping.
The viewer-side fill light provides diffuse illumination and a restrained
specular highlight on the teapot.

SSIL uses a 150 mm radius and 1.0 intensity to complement the baked lighting.

The teapot's source and attribution are in [models/TEAPOT_ATTRIBUTION.txt](models/TEAPOT_ATTRIBUTION.txt).

## Capture a comparison frame

While the app is running, press **S** to save the current view as a PNG in your
Downloads folder. The screenshot includes the live webcam reflection, and the
brief save confirmation appears only after the image is captured.

```sh
/Applications/Godot.app/Contents/MacOS/Godot --path godot -- --capture /tmp/holoframe-godot.png
```

The app saves one PNG after two seconds and exits. The UDP pose and image
ports are 55123 and 55124, bound to localhost.
