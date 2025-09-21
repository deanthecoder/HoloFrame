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
    VirtualFileSystem,
    getModelPath,
    TextNode,
    Vec3,
    Vec4,
    WindowProperties,
    loadPrcFileData,
)

from config import AppConfig
from head_pose_tracker import HeadPoseTracker
from rendering import CubeRenderer


class HoloFrameApp(ShowBase):
    def __init__(self) -> None:
        ShowBase.__init__(self)

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
            props.setSize(800, 600)
            props.setFullscreen(False)

        if self.win is not None:
            self.win.requestProperties(props)

        self.app_config = AppConfig()

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
            scale=0.05,
            mayChange=True,
        )
        self.fps_text = OnscreenText(
            text="FPS: --",
            pos=(-1.3, 0.85),
            align=TextNode.ALeft,
            fg=(0.8, 0.8, 1.0, 1.0),
            scale=0.05,
            mayChange=True,
        )

        self._log_available_models()
        self._build_scene()
        self._apply_camera_pose(self.cam_pos_display)

        self.taskMgr.add(self._update_task, "holoframe-update")

    def _build_scene(self) -> None:
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

        max_dim = max(size.x, size.y, size.z, 1e-6)
        scale_factor = target_size_m / max_dim
        model_root.setScale(scale_factor)

        depth_half = (size.y * 0.5) * scale_factor
        model_root.setPos(0.0, -depth_half, 0.0)

        if self.app_config.model_path == "models/box":
            model_root.setColor(0.25, 0.6, 0.95, 1.0)

        model_root.setShaderAuto()

        ambient = AmbientLight("ambient")
        ambient.setColor(Vec4(0.12, 0.12, 0.16, 1.0))
        ambient_node = scene_root.attachNewNode(ambient)

        key = DirectionalLight("key")
        key.setColor(Vec4(0.9, 0.9, 0.9, 1.0))
        key.setDirection(Vec3(0.0, 1.0, -0.2))
        key_node = scene_root.attachNewNode(key)

        self.render.clearLight()
        self.render.setLight(ambient_node)
        self.render.setLight(key_node)

        self._scene_root = scene_root
        self._cube_node = model_root

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
    app.run()

if __name__ == "__main__":
    main()
