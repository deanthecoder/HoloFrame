# Setup:
#   python -m pip install --upgrade pip
#   pip install opencv-python mediapipe numpy panda3d

import cv2
import numpy as np
import time
import math

from direct.showbase.ShowBase import ShowBase
from direct.gui.OnscreenText import OnscreenText
from direct.task import Task
from panda3d.core import (
    AmbientLight,
    DirectionalLight,
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    PerspectiveLens,
    Spotlight,
    PointLight,
    VirtualFileSystem,
    getModelPath,
    TextNode,
    Vec3,
    Vec4,
    LVector3,
    WindowProperties,
    loadPrcFileData,
)

from config import AppConfig
from head_pose_tracker import HeadPoseTracker
from rendering import CubeRenderer


class HoloFrameApp(ShowBase):
    """Main Panda3D application that renders the tracked model inside a room."""
    def __init__(self) -> None:
        ShowBase.__init__(self)

        self.render.setShaderAuto()

        self.disableMouse()
        self.setBackgroundColor(0, 0, 0)
        self.accept("escape", self._handle_exit)

        if self.camLens is not None:
            self.camLens.setNearFar(0.001, 1000.0)

        if self.win is not None:
            self.win.setCloseRequestEvent("holoframe-close")
            self.accept("holoframe-close", self._handle_exit)

        props = WindowProperties()
        props.setTitle("HoloFrame (ESC to quit)")
        props.setUndecorated(True)

        display_w = self.pipe.getDisplayWidth() if self.pipe else 0
        display_h = self.pipe.getDisplayHeight() if self.pipe else 0
        if display_w > 0 and display_h > 0:
            props.setSize(display_w, display_h)
            props.setFullscreen(True)
        else:
            raise RuntimeError("Display size is not available from the graphics pipe")

        if self.win is not None:
            self.win.requestProperties(props)

        self.app_config = AppConfig()

        target_size_m = max(1e-3, self.app_config.model_max_size_mm / 1000.0)
        self.room_width = target_size_m * 2.0
        self.room_height = target_size_m * 2.0
        self.room_depth = target_size_m * 3.0
        self._room_dimension_step = 0.1
        self._room_depth_step = 0.1
        self._room_min_width = 0.3
        self._room_min_height = 0.3
        self._room_min_depth = 0.3
        self._spotlight_node = None

        self.accept("arrow_left", self._decrease_room_width)
        self.accept("arrow_right", self._increase_room_width)
        self.accept("arrow_down", self._decrease_room_height)
        self.accept("arrow_up", self._increase_room_height)
        self.accept("l", self._decrease_room_depth)
        self.accept("p", self._increase_room_depth)

        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            raise RuntimeError("Webcam not found")

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)

        self.tracker = HeadPoseTracker(self.app_config)
        self.cube_renderer = CubeRenderer(self.app_config)

        self.default_cam_pos = np.array(self.app_config.default_camera_pos_mm, dtype=np.float32)
        self.cam_pos_display = self.default_cam_pos.copy()
        self.fps_avg = None
        self.t_prev = time.time()
        self.motion_t_prev = self.t_prev

        self.pose_text = OnscreenText(
            text="Initializing pose",
            pos=(-1.3, 0.93),
            align=TextNode.ALeft,
            fg=(0.95, 0.95, 0.95, 1.0),
            scale=0.025,
            mayChange=True,
        )
        self.fps_text = OnscreenText(
            text="FPS: --",
            pos=(-1.3, 0.85),
            align=TextNode.ALeft,
            fg=(0.8, 0.8, 1.0, 1.0),
            scale=0.025,
            mayChange=True,
        )
        self.room_text = OnscreenText(
            text="Room: --",
            pos=(-1.3, 0.77),
            align=TextNode.ALeft,
            fg=(0.9, 0.9, 0.9, 1.0),
            scale=0.025,
            mayChange=True,
        )

        self._log_available_models()
        self._build_scene()
        self._apply_camera_pose(self.cam_pos_display)

        self.taskMgr.add(self._update_task, "holoframe-update")

    def _build_scene(self) -> None:
        """Load the primary model and construct lighting and room geometry."""
        target_size_m = max(1e-3, self.app_config.model_max_size_mm / 1000.0)

        scene_root = self.render.attachNewNode("holoframe-scene")
        model_root = scene_root.attachNewNode("cube-root")

        model = self.loader.loadModel(self.app_config.model_path)
        if model.isEmpty():
            raise RuntimeError(
                f"Failed to load model '{self.app_config.model_path}'. Update config.model_path to a valid Panda3D model."
            )

        model.reparentTo(model_root)

        min_bound, max_bound = model.getTightBounds()
        if min_bound is None or max_bound is None:
            raise RuntimeError(f"Failed to compute bounds for model '{self.app_config.model_path}'")

        center = (min_bound + max_bound) * 0.5
        size = max_bound - min_bound
        model.setPos(-center)
        model_root.setH(-25)

        max_dim = max(size.x, size.y, size.z, 1e-6)
        scale_factor = target_size_m / max_dim
        model_root.setScale(scale_factor)

        depth_half = size.y * 0.5 * scale_factor
        model_root.setPos(0.0, depth_half + 0.05, 0.0)

        if self.app_config.model_path == "models/box":
            model_root.setColor(0.25, 0.6, 0.95, 1.0)

        model_root.setShaderAuto()

        # --- Lighting setup ---
        # Tiny ambient to lift darkest areas without washing out shadows
        ambient = AmbientLight("ambient")
        ambient.setColor(Vec4(0.06, 0.06, 0.06, 1.0) * 0.1)
        ambient_node = scene_root.attachNewNode(ambient)

        # Key light: ceiling spotlight (only shadow-casting light)
        spot_light = Spotlight("ceiling-spot")
        spot_light.setColor(Vec4(1.0, 0.98, 0.92, 1.0) * 1.4)
        spot_lens = PerspectiveLens()
        spot_lens.setFov(60.0)
        spot_lens.setNearFar(0.02, 5.0)
        spot_light.setLens(spot_lens)
        spot_light.setShadowCaster(True, 1024, 1024)
        self._spotlight_node = scene_root.attachNewNode(spot_light)

        # Wall bounce fills (no shadows): slight tints to mimic color bleed
        left_fill = DirectionalLight("left_bounce")
        left_fill.setColor((0.10, 0.15, 0.10, 1))   # green-ish if left wall is green
        left_node = scene_root.attachNewNode(left_fill)
        left_node.setHpr(90, -10, 0)

        right_fill = DirectionalLight("right_bounce")
        right_fill.setColor((0.15, 0.10, 0.10, 1))  # red-ish if right wall is red
        right_node = scene_root.attachNewNode(right_fill)
        right_node.setHpr(-90, -10, 0)

        # Floor bounce: gentle upward fill (no shadows)
        up_fill = DirectionalLight("floor_hemi")
        up_fill.setColor((0.12, 0.12, 0.12, 1))
        up_node = scene_root.attachNewNode(up_fill)
        up_node.setHpr(0, 60, 0)  # tilt upward to light undersides

        # Apply lights (spot is positioned later in _update_room_lighting)
        self.render.clearLight()
        self.render.setLight(ambient_node)
        self.render.setLight(self._spotlight_node)
        self.render.setLight(left_node)
        self.render.setLight(right_node)
        self.render.setLight(up_node)

        self._room_node = scene_root.attachNewNode("cornell-room")
        self._room_node.setTwoSided(True)
        self._rebuild_room_geometry()
        self._update_room_lighting()

        self._scene_root = scene_root
        self._cube_node = model_root

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
        floor.setColor(0.7, 0.7, 0.7, 1.0)

        ceiling = self._room_node.attachNewNode(
            self._make_panel("room-ceiling", ceiling_corners, (0.0, 0.0, -1.0))
        )
        ceiling.setColor(0.8, 0.8, 0.8, 1.0)

        left_wall = self._room_node.attachNewNode(
            self._make_panel("room-left", left_wall_corners, (1.0, 0.0, 0.0))
        )
        left_wall.setColor(0.63, 0.06, 0.06, 1.0)

        right_wall = self._room_node.attachNewNode(
            self._make_panel("room-right", right_wall_corners, (-1.0, 0.0, 0.0))
        )
        right_wall.setColor(0.16, 0.6, 0.18, 1.0)

        back_wall = self._room_node.attachNewNode(
            self._make_panel("room-back", back_wall_corners, (0.0, -1.0, 0.0))
        )
        back_wall.setColor(0.8, 0.8, 0.8, 1.0)

        self._update_room_lighting()

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

    def _update_room_lighting(self) -> None:
        """Reposition the ceiling spotlight so it stays centered above the room."""
        if self._spotlight_node is None:
            raise RuntimeError("Spotlight node is not set")

        height = max(self._room_min_height, float(self.room_height))
        depth = max(self._room_min_depth, float(self.room_depth))

        # Centered under the ceiling, aimed toward the room center
        self._spotlight_node.setPos(0.0, -depth * 0.5, height * 0.5)
        self._spotlight_node.lookAt(0.0, depth * 0.5, 0.0)

    def _log_available_models(self) -> None:
        vfs = VirtualFileSystem.getGlobalPtr()
        model_path = getModelPath()
        found = set()

        def scan(directory, prefix: str) -> None:
            if directory.empty():
                return
            file_list = vfs.scanDirectory(directory)
            if file_list is None:
                return
            for i in range(file_list.getNumFiles()):
                vfile = file_list.getFile(i)
                filename = vfile.getFilename()
                basename = filename.getBasename()
                if vfile.isDirectory():
                    scan(filename, prefix + basename + "/")
                    continue
                name_lower = basename.lower()
                if name_lower.endswith((".egg", ".bam", ".egg.pz", ".bam.pz")):
                    trimmed = basename
                    if trimmed.lower().endswith(".pz"):
                        trimmed = trimmed[:-3]
                    if trimmed.lower().endswith(".egg"):
                        trimmed = trimmed[:-4]
                    elif trimmed.lower().endswith(".bam"):
                        trimmed = trimmed[:-4]
                    found.add(prefix + trimmed)

        for i in range(model_path.getNumDirectories()):
            scan(model_path.getDirectory(i), "")

        if not found:
            print("[HoloFrame] No Panda3D models found on model-path")
            return

        print("[HoloFrame] Panda3D models available:")
        for name in sorted(found):
            print(f"  - {name}")

    def _apply_camera_pose(self, cam_pos_mm: np.ndarray) -> None:
        pos = cam_pos_mm.astype(np.float32)
        x_m = -float(pos[0]) * 0.001
        y_m = -float(pos[2]) * 0.001
        z_m = -float(pos[1]) * 0.001

        if y_m > -0.05:
            y_m = -0.05

        self.camera.setPos(x_m, y_m, z_m)
        self.camera.lookAt(0.0, 0.0, 0.0)

    def _update_task(self, task: Task) -> int:
        ok, frame = self.cap.read()
        if not ok:
            return Task.cont

        frame_time = time.time()
        dt_motion = max(0.0, frame_time - self.motion_t_prev)

        h, w = frame.shape[:2]
        focal = w
        K = np.array(
            [[focal, 0.0, w / 2.0], [0.0, focal, h / 2.0], [0.0, 0.0, 1.0]],
            dtype=np.float32,
        )
        dist = np.zeros((4, 1), dtype=np.float32)

        estimate = self.tracker.process(frame, frame_time, K, dist)

        if estimate.detected and estimate.position_mm is not None:
            self.cam_pos_display = estimate.position_mm.astype(np.float32)
            pose_text = (
                f"x={self.cam_pos_display[0]:+.1f}  "
                f"y={self.cam_pos_display[1]:+.1f}  "
                f"z={self.cam_pos_display[2]:+.1f}"
            )
        else:
            pose_text = "No face"
            lerp = 1.0 - math.exp(-self.app_config.recenter_lerp_rate * dt_motion)
            lerp = float(min(max(lerp, 0.0), 1.0))
            self.cam_pos_display = self.cam_pos_display + (
                self.default_cam_pos - self.cam_pos_display
            ) * lerp
            self.cam_pos_display = self.cam_pos_display.astype(np.float32)

        # Cube renderer retained for future 3D work; intentionally not invoked for now.

        self.motion_t_prev = frame_time

        t_now = time.time()
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
    loadPrcFileData("", "load-display pandagl")
    loadPrcFileData("", "framebuffer-srgb true")
    loadPrcFileData("", "win-size 800 600")
    loadPrcFileData("", "undecorated 1")

    app = HoloFrameApp()
    app.run()

if __name__ == "__main__":
    main()
