# Setup:
#   python -m pip install --upgrade pip
#   python -m pip install -r requirements.txt

import cv2
import numpy as np
import time
import math

# MediaPipe must load before Panda3D to avoid a native DLL conflict on Windows.
from config import AppConfig
from head_pose_tracker import HeadPoseEstimate, HeadPoseTracker
from display_selection import active_displays, select_display

from direct.showbase.ShowBase import ShowBase
from direct.gui.OnscreenText import OnscreenText
from direct.task import Task
from panda3d.core import (
    AmbientLight,
    BitMask32,
    DirectionalLight,
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    LineSegs,
    Material,
    PerspectiveLens,
    Spotlight,
    TextNode,
    TransparencyAttrib,
    Vec3,
    Vec4,
    WindowProperties,
    loadPrcFileData,
)

from projection import apply_screen_projection


class HoloFrameApp(ShowBase):
    """Main Panda3D application that renders the tracked model inside a room."""
    def __init__(self) -> None:
        self.app_config = AppConfig()
        self._hud_visible = True
        self._instructions_visible = False
        self._fullscreen = True
        displays = active_displays()
        display = select_display(displays, self.app_config.monitor_index)
        for i, candidate in enumerate(displays):
            print(f"[HoloFrame] Display {i}: {candidate}")
        ShowBase.__init__(self, windowType="none")

        props = WindowProperties()
        props.setTitle("HoloFrame (ESC to quit)")
        props.setUndecorated(True)
        if display is not None:
            # Borderless desktop pixels select the actual monitor, including negative origins.
            props.setOrigin(display.x, display.y)
            props.setSize(display.width, display.height)
            props.setFullscreen(False)
            print(f"[HoloFrame] Selected display: {display}")
        else:
            self.makeDefaultPipe()
            width = self.pipe.getDisplayWidth() if self.pipe else 0
            height = self.pipe.getDisplayHeight() if self.pipe else 0
            if width <= 0 or height <= 0:
                raise RuntimeError("Display size is not available from the graphics pipe")
            props.setSize(width, height)
            props.setFullscreen(True)
        self._fullscreen_properties = WindowProperties(props)
        self.openDefaultWindow(props=props)
        if self.win is None:
            raise RuntimeError("Unable to open the HoloFrame window")
        self.screen_height_mm = (self.app_config.screen_width_mm *
                                 self.win.getYSize() / self.win.getXSize())

        self.disableMouse()
        self.setBackgroundColor(0, 0, 0)
        self.accept("escape", self._handle_exit)

        if self.camLens is not None:
            self.camLens.setNearFar(0.001, 1000.0)

        if self.win is not None:
            self.win.setCloseRequestEvent("holoframe-close")
            self.accept("holoframe-close", self._handle_exit)

        target_size_m = max(1e-3, self.app_config.model_max_size_mm / 1000.0)
        self.room_width = self.app_config.screen_width_mm / 1000.0
        self.room_height = self.screen_height_mm / 1000.0
        self.room_depth = target_size_m * 3.0
        self._room_dimension_step = 0.1
        self._room_depth_step = 0.1
        self._room_min_width = 0.1
        self._room_min_height = 0.1
        self._room_min_depth = 0.3
        self._spotlight_node = None

        self.accept("arrow_left", self._decrease_room_width)
        self.accept("arrow_right", self._increase_room_width)
        self.accept("arrow_down", self._decrease_room_height)
        self.accept("arrow_up", self._increase_room_height)
        self.accept("l", self._decrease_room_depth)
        self.accept("p", self._increase_room_depth)
        for event in ("w", "w-repeat"):
            self.accept(event, self._move_model_depth, [-0.01])
        for event in ("s", "s-repeat"):
            self.accept(event, self._move_model_depth, [0.01])
        self.accept("c", self._set_model_depth, [0.0])
        self.accept("r", self._reset_model_depth)

        self.cap = cv2.VideoCapture(self.app_config.webcam_index)
        if not self.cap.isOpened():
            raise RuntimeError("Webcam not found")

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)

        self.tracker = HeadPoseTracker(self.app_config, self.screen_height_mm)

        self.default_cam_pos = np.array(self.app_config.default_camera_pos_mm, dtype=np.float32)
        self.cam_pos_display = self.default_cam_pos.copy()
        self.fps_avg = None
        self.t_prev = time.perf_counter()
        self.motion_t_prev = self.t_prev

        self.pose_text = OnscreenText(
            text="Initializing pose",
            parent=self.a2dTopLeft,
            pos=(0.04, -0.07),
            align=TextNode.ALeft,
            fg=(0.95, 0.95, 0.95, 1.0),
            scale=0.025,
            mayChange=True,
        )
        self.fps_text = OnscreenText(
            text="FPS: --",
            parent=self.a2dTopLeft,
            pos=(0.04, -0.15),
            align=TextNode.ALeft,
            fg=(0.8, 0.8, 1.0, 1.0),
            scale=0.025,
            mayChange=True,
        )
        self.room_text = OnscreenText(
            text="Room: --",
            parent=self.a2dTopLeft,
            pos=(0.04, -0.23),
            align=TextNode.ALeft,
            fg=(0.9, 0.9, 0.9, 1.0),
            scale=0.025,
            mayChange=True,
        )

        self.model_depth_text = OnscreenText(
            text="", parent=self.a2dTopLeft, pos=(0.04, -0.31),
            align=TextNode.ALeft, fg=(0.95, 0.95, 0.95, 1.0),
            scale=0.025, mayChange=True,
        )

        self.instructions_text = OnscreenText(
            text="ESC: quit   F: fullscreen   H: HUD   M: next model\n"
                 "Arrows: room size   L/P: room depth\n"
                 "W/S: model depth   C: screen plane   R: reset   ?: help",
            pos=(0, 0.75), scale=0.035, align=TextNode.ACenter,
            fg=(0.95, 0.95, 0.9, 1), mayChange=True)
        self.instructions_text.hide()
        self._model_cycle = list(dict.fromkeys([
            self.app_config.model_path, "models/teapot", "models/panda",
            "models/smiley", "models/environment"]))
        self._model_index = 0
        self.accept("m", self._cycle_model)
        self.accept("h", self._toggle_hud_visibility)
        self.accept("?", self._toggle_instructions)
        self.accept("shift-/", self._toggle_instructions)
        self.accept("f", self._toggle_fullscreen)
        self._build_scene()
        self._initial_model_depth_m = self._cube_node.getY()
        self._reset_model_depth()
        self._apply_camera_pose(self.cam_pos_display)

        self.taskMgr.add(self._update_task, "holoframe-update")

    def _build_scene(self) -> None:
        """Load the primary model and construct lighting and room geometry."""
        target_size_m = max(1e-3, self.app_config.model_max_size_mm / 1000.0)

        scene_root = self.render.attachNewNode("holoframe-scene")
        scene_root.setShaderAuto()
        model_root = scene_root.attachNewNode("cube-root")

        self._cube_node = model_root
        self._apply_model(self._model_cycle[self._model_index])
        model_root.setY(self.app_config.model_depth_mm * 0.001)

        ceramic = Material("glazed-ceramic")
        ceramic.setDiffuse(Vec4(0.72, 0.77, 0.80, 1.0))
        ceramic.setAmbient(Vec4(0.72, 0.77, 0.80, 1.0))
        ceramic.setSpecular(Vec4(0.28, 0.28, 0.28, 1.0))
        ceramic.setShininess(48.0)
        model_root.setMaterial(ceramic, 1)
        model_root.setDepthOffset(1)  # Suppress self-shadow acne on thin parts of the model.

        ambient = AmbientLight("ambient")
        ambient.setColor(Vec4(0.22, 0.24, 0.28, 1.0))
        ambient_node = scene_root.attachNewNode(ambient)

        key = DirectionalLight("key")
        key.setColor(Vec4(0.20, 0.23, 0.28, 1.0))
        key.setDirection(Vec3(-0.5, 1.0, -0.2))
        key_node = scene_root.attachNewNode(key)

        self.render.clearLight()
        self.render.setLight(ambient_node)
        self.render.setLight(key_node)

        spot_light = Spotlight("front-key")
        spot_light.setColor(Vec4(0.95, 0.88, 0.76, 1.0))
        spot_light.setShadowCaster(True, 2048, 2048)
        spot_light.setCameraMask(BitMask32.bit(1))
        spot_lens = PerspectiveLens()
        spot_lens.setFov(85.0)
        spot_lens.setNearFar(0.05, 3.0)
        spot_light.setLens(spot_lens)
        self._spotlight_node = scene_root.attachNewNode(spot_light)
        self.render.setLight(self._spotlight_node)

        self._room_node = scene_root.attachNewNode("cornell-room")
        self._prop_models = {
            "box": self.loader.loadModel("models/box"),
            "sphere": self.loader.loadModel("models/misc/sphere"),
        }
        self._rebuild_room_geometry()
        self._update_room_lighting()

        self._scene_root = scene_root
        self._cube_node = model_root

    def _apply_model(self, model_path: str) -> None:
        """Replace the foreground model while retaining its selected depth."""
        model_root = self._cube_node
        for child in model_root.getChildren():
            child.removeNode()
        target_size_m = self.app_config.model_max_size_mm / 1000.0
        model_root.clearColor()
        model = self.loader.loadModel(model_path)
        if model.isEmpty():
            raise RuntimeError(
                f"Failed to load model '{model_path}'. Update config.model_path to a valid Panda3D model."
            )

        model.reparentTo(model_root)

        min_bound, max_bound = model.getTightBounds()
        if min_bound is None or max_bound is None:
            raise RuntimeError(f"Failed to compute bounds for model '{model_path}'")

        center = (min_bound + max_bound) * 0.5
        size = max_bound - min_bound
        model.setPos(-center)

        max_dim = max(size.x, size.y, size.z, 1e-6)
        scale_factor = target_size_m / max_dim
        model_root.setScale(scale_factor)


        if model_path == "models/box":
            model_root.setColor(0.25, 0.6, 0.95, 1.0)


    def _cycle_model(self) -> None:
        """Advance through the bundled models."""
        self._model_index = (self._model_index + 1) % len(self._model_cycle)
        self._apply_model(self._model_cycle[self._model_index])

    def _toggle_fullscreen(self) -> None:
        """Toggle a windowed preview and the originally selected full-monitor view."""
        self._fullscreen = not self._fullscreen
        props = WindowProperties(self._fullscreen_properties)
        if not self._fullscreen:
            props.setFullscreen(False)
            props.setUndecorated(False)
            props.setSize(960, 600)
        self.win.requestProperties(props)

    def _toggle_instructions(self) -> None:
        """Toggle the controls overlay."""
        self._instructions_visible = not self._instructions_visible
        self._apply_hud_visibility()

    def _toggle_hud_visibility(self) -> None:
        """Toggle all HUD widgets."""
        self._hud_visible = not self._hud_visible
        self._apply_hud_visibility()

    def _apply_hud_visibility(self) -> None:
        """Keep the depth readout and help consistent with the HUD toggle."""
        for widget in (self.pose_text, self.fps_text, self.room_text, self.model_depth_text):
            widget.show() if self._hud_visible else widget.hide()
        if self._hud_visible and self._instructions_visible:
            self.instructions_text.show()
        else:
            self.instructions_text.hide()

    def _make_panel(self, name: str, corners, normal) -> GeomNode:
        """Create a rectangular panel geometry from four corner points and a normal."""
        vertex_format = GeomVertexFormat.getV3n3()
        vertex_data = GeomVertexData(name, vertex_format, Geom.UHStatic)
        vertex_data.setNumRows(4)

        vertex_writer = GeomVertexWriter(vertex_data, "vertex")
        normal_writer = GeomVertexWriter(vertex_data, "normal")

        for corner in corners:
            vertex_writer.addData3f(*corner)
            normal_writer.addData3f(*normal)

        triangles = GeomTriangles(Geom.UHStatic)
        triangles.addVertices(0, 1, 2)
        triangles.addVertices(0, 2, 3)

        geom = Geom(vertex_data)
        geom.addPrimitive(triangles)

        panel = GeomNode(name)
        panel.addGeom(geom)
        return panel

    def _rebuild_room_geometry(self) -> None:
        """Regenerate the Cornell-box style room based on the current dimensions."""
        if getattr(self, "_room_node", None) is None:
            return

        for child in self._room_node.getChildren():
            child.removeNode()

        width = max(self._room_min_width, float(self.room_width))
        height = max(self._room_min_height, float(self.room_height))
        depth = max(self._room_min_depth, float(self.room_depth))

        half_w = width * 0.5
        half_h = height * 0.5

        floor_corners = [
            (-half_w, 0.0, -half_h),
            (half_w, 0.0, -half_h),
            (half_w, depth, -half_h),
            (-half_w, depth, -half_h),
        ]
        ceiling_corners = [
            (-half_w, depth, half_h),
            (half_w, depth, half_h),
            (half_w, 0.0, half_h),
            (-half_w, 0.0, half_h),
        ]
        left_wall_corners = [
            (-half_w, 0.0, -half_h),
            (-half_w, depth, -half_h),
            (-half_w, depth, half_h),
            (-half_w, 0.0, half_h),
        ]
        right_wall_corners = [
            (half_w, 0.0, half_h),
            (half_w, depth, half_h),
            (half_w, depth, -half_h),
            (half_w, 0.0, -half_h),
        ]
        back_wall_corners = [
            (-half_w, depth, half_h),
            (-half_w, depth, -half_h),
            (half_w, depth, -half_h),
            (half_w, depth, half_h),
        ]

        floor = self._room_node.attachNewNode(
            self._make_panel("room-floor", floor_corners, (0.0, 0.0, 1.0))
        )
        floor.setColor(0.70, 0.67, 0.61, 1.0)

        ceiling = self._room_node.attachNewNode(
            self._make_panel("room-ceiling", ceiling_corners, (0.0, 0.0, -1.0))
        )
        ceiling.setColor(0.8, 0.8, 0.8, 1.0)

        left_wall = self._room_node.attachNewNode(
            self._make_panel("room-left", left_wall_corners, (1.0, 0.0, 0.0))
        )
        left_wall.setColor(0.44, 0.20, 0.17, 1.0)

        right_wall = self._room_node.attachNewNode(
            self._make_panel("room-right", right_wall_corners, (-1.0, 0.0, 0.0))
        )
        right_wall.setColor(0.19, 0.34, 0.29, 1.0)

        back_wall = self._room_node.attachNewNode(
            self._make_panel("room-back", back_wall_corners, (0.0, -1.0, 0.0))
        )
        back_wall.setColor(0.76, 0.73, 0.67, 1.0)

        self._add_room_grid(width, height, depth)
        self._add_room_objects(width, height, depth)

        self._update_room_lighting()

    def _add_room_objects(self, width: float, height: float, depth: float) -> None:
        """Place three floor-supported reference objects at distinct, room-relative depths."""
        def place(name, shape, dimensions, x, y, heading, color):
            root = self._room_node.attachNewNode(name)
            model = self._prop_models[shape].copyTo(root)
            low, high = model.getTightBounds()
            size = high - low
            model.setPos(-(low + high) * 0.5)
            root.setScale(*(dimension / size[i] for i, dimension in enumerate(dimensions)))
            root.setH(heading)
            root.setPos(x, y, -height * 0.5 + dimensions[2] * 0.5)
            root.setTextureOff(1)
            root.setColor(1, 1, 1, 1, 1)
            material = Material(name)
            material.setDiffuse(Vec4(*color, 1))
            material.setAmbient(Vec4(*color, 1))
            material.setSpecular(Vec4(0.06, 0.06, 0.06, 1))
            material.setShininess(18)
            root.setMaterial(material, 1)
            root.setDepthOffset(1)

        side = min(0.07, width * 0.21, depth * 0.19)
        place("tall-back-left-block", "box", (side, side, height * 0.65),
              -width * 0.28, depth * 0.72, 18, (0.78, 0.75, 0.68))
        place("short-mid-right-block", "box", (side * 0.8, side * 0.8, height * 0.26),
              width * 0.20, depth * 0.35, -15, (0.65, 0.67, 0.66))
        diameter = min(0.045, width * 0.18, height * 0.24)
        place("distant-sphere", "sphere", (diameter,) * 3,
              width * 0.40, depth * 0.84, 0, (0.72, 0.65, 0.52))

    def _add_room_grid(self, width: float, height: float, depth: float) -> None:
        """Add fixed 50 mm seams so the floor and back wall reveal perspective and parallax."""
        lines = LineSegs("room-seams")
        lines.setThickness(1.0)
        lines.setColor(0.10, 0.10, 0.10, 0.18)
        half_w, half_h = width * 0.5, height * 0.5
        offset = 0.0003  # Keep seams just above the surfaces to avoid z-fighting.
        for x in np.arange(-half_w + 0.05, half_w, 0.05):
            lines.moveTo(x, 0, -half_h + offset)
            lines.drawTo(x, depth, -half_h + offset)
            lines.moveTo(x, depth - offset, -half_h)
            lines.drawTo(x, depth - offset, half_h)
        for y in np.arange(0.05, depth, 0.05):
            lines.moveTo(-half_w, y, -half_h + offset)
            lines.drawTo(half_w, y, -half_h + offset)
        for z in np.arange(-half_h + 0.05, half_h, 0.05):
            lines.moveTo(-half_w, depth - offset, z)
            lines.drawTo(half_w, depth - offset, z)
        seams = self._room_node.attachNewNode(lines.create())
        seams.setLightOff()
        seams.setShaderOff()
        seams.setTransparency(TransparencyAttrib.MAlpha)
        seams.hide(BitMask32.bit(1))  # Surface markings must not cast their own shadows.

    def _set_room_width(self, width: float) -> None:
        """Apply a new room width value and rebuild the geometry."""
        self.room_width = max(self._room_min_width, float(width))
        self._rebuild_room_geometry()

    def _set_room_height(self, height: float) -> None:
        """Apply a new room height value and rebuild the geometry."""
        self.room_height = max(self._room_min_height, float(height))
        self._rebuild_room_geometry()

    def _set_room_depth(self, depth: float) -> None:
        """Apply a new room depth value and rebuild the geometry."""
        self.room_depth = max(self._room_min_depth, float(depth))
        self._rebuild_room_geometry()

    def _increase_room_width(self) -> None:
        """Handle keyboard input to widen the room."""
        self._set_room_width(self.room_width + self._room_dimension_step)

    def _decrease_room_width(self) -> None:
        """Handle keyboard input to narrow the room."""
        self._set_room_width(self.room_width - self._room_dimension_step)

    def _increase_room_height(self) -> None:
        """Handle keyboard input to raise the ceiling."""
        self._set_room_height(self.room_height + self._room_dimension_step)

    def _decrease_room_height(self) -> None:
        """Handle keyboard input to lower the ceiling."""
        self._set_room_height(self.room_height - self._room_dimension_step)

    def _increase_room_depth(self) -> None:
        """Handle keyboard input to push the back wall farther away."""
        self._set_room_depth(self.room_depth + self._room_depth_step)

    def _decrease_room_depth(self) -> None:
        """Handle keyboard input to pull the back wall closer."""
        self._set_room_depth(self.room_depth - self._room_depth_step)

    def _set_model_depth(self, depth_m: float) -> None:
        """Move only the model; zero centers it on the physical screen plane."""
        depth_m = min(0.2, max(-0.2, float(depth_m)))
        self._cube_node.setY(depth_m)
        position = "at screen" if abs(depth_m) < 0.0005 else (
            "behind screen" if depth_m > 0 else "in front of screen"
        )
        self.model_depth_text.setText(
            f"Model center: {abs(depth_m) * 1000:.0f}mm {position}\n"
            "W/S: nearer/further   C: screen plane   R: reset"
        )

    def _move_model_depth(self, step_m: float) -> None:
        """Adjust the model depth in 10 mm keyboard steps."""
        self._set_model_depth(self._cube_node.getY() + step_m)

    def _reset_model_depth(self) -> None:
        """Restore the configured starting depth."""
        self._set_model_depth(self._initial_model_depth_m)

    def _update_room_lighting(self) -> None:
        """Light from above the viewer side so protruding objects cast shadows into the room."""
        if self._spotlight_node is None:
            raise RuntimeError("Spotlight node is not set")

        height = max(self._room_min_height, float(self.room_height))
        depth = max(self._room_min_depth, float(self.room_depth))

        self._spotlight_node.setPos(-0.12, -0.45, height * 0.5 + 0.12)
        self._spotlight_node.lookAt(0.0, depth * 0.3, height * -0.5)
        self._spotlight_node.node().getLens().setFar(max(3.0, depth + height + self.room_width))

    def _apply_camera_pose(self, cam_pos_mm: np.ndarray) -> None:
        """Keep the screen fixed while moving the eye and its off-axis frustum."""
        apply_screen_projection(self.camera, self.camLens, cam_pos_mm,
                                self.app_config.screen_width_mm, self.screen_height_mm)

    def _update_task(self, task: Task) -> int:
        ok, frame = self.cap.read()
        frame_time = time.perf_counter()
        dt_motion = max(0.0, frame_time - self.motion_t_prev)
        estimate = HeadPoseEstimate(False, None)
        if ok and frame is not None:
            h, w = frame.shape[:2]
            focal = w  # Approximate webcam intrinsics; actual returned frame dimensions.
            K = np.array(
                [[focal, 0.0, w / 2.0], [0.0, focal, h / 2.0], [0.0, 0.0, 1.0]],
                dtype=np.float32,
            )
            dist = np.zeros((4, 1), dtype=np.float32)
            estimate = self.tracker.process(frame, frame_time, K, dist)
        else:
            self.tracker.mark_lost()

        if estimate.detected and estimate.position_mm is not None:
            self.cam_pos_display = estimate.position_mm.astype(np.float32)
            pose_text = (
                f"x={self.cam_pos_display[0]:+.1f}  "
                f"y={self.cam_pos_display[1]:+.1f}  "
                f"z={self.cam_pos_display[2]:+.1f}"
            )
        else:
            pose_text = "No face" if ok and frame is not None else "Camera unavailable"
            lerp = 1.0 - math.exp(-self.app_config.recenter_lerp_rate * dt_motion)
            lerp = float(min(max(lerp, 0.0), 1.0))
            self.cam_pos_display = self.cam_pos_display + (
                self.default_cam_pos - self.cam_pos_display
            ) * lerp
            self.cam_pos_display = self.cam_pos_display.astype(np.float32)

        self.motion_t_prev = frame_time

        t_now = time.perf_counter()
        fps = 1.0 / max(1e-6, (t_now - self.t_prev))
        self.t_prev = t_now
        self.fps_avg = fps if self.fps_avg is None else (self.fps_avg * 0.9 + fps * 0.1)

        self.pose_text.setText(pose_text)
        self._apply_camera_pose(self.cam_pos_display)

        self.fps_text.setText(f"FPS: {self.fps_avg:.1f}")

        width = max(self._room_min_width, float(self.room_width))
        height = max(self._room_min_height, float(self.room_height))
        depth = max(self._room_min_depth, float(self.room_depth))
        self.room_text.setText(
            f"Room W:{width:.2f}m  H:{height:.2f}m  D:{depth:.2f}m"
        )

        return Task.cont

    def _handle_exit(self) -> None:
        self._cleanup()
        self.userExit()

    def _cleanup(self) -> None:
        if getattr(self, "tracker", None) is not None:
            self.tracker.close()
            self.tracker = None
        if getattr(self, "cap", None) is not None:
            self.cap.release()
            self.cap = None

    def destroy(self) -> None:
        self._cleanup()
        super().destroy()


# ---------- Main ----------
def main():
    loadPrcFileData("", "win-size 800 600")
    loadPrcFileData("", "undecorated 1")

    app = HoloFrameApp()
    try:
        app.run()
    finally:
        app.destroy()

if __name__ == "__main__":
    main()
