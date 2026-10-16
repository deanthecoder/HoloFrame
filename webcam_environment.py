"""Low-frequency webcam lighting and a partial, world-aligned reflection environment."""

import math

import cv2
import numpy as np
from panda3d.core import DirectionalLight, TexGenAttrib, Texture, TextureStage, Vec3


def prepare_frame(frame_bgr):
    """Reduce detail before estimating illumination; work in approximately linear RGB."""
    height = max(8, round(64 * frame_bgr.shape[0] / frame_bgr.shape[1]))
    small = cv2.resize(frame_bgr, (64, height), interpolation=cv2.INTER_AREA)
    rgb = small[:, :, ::-1].astype(np.float32) / 255.0
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    return cv2.GaussianBlur(linear, (0, 0), 3.0)


def reflection_cube(rgb, size=64):
    """Project the camera's limited field of view into -Y; fill unseen directions softly.

    Faces use OpenGL's +X, -X, +Y, -Y, +Z, -Z order and bottom-up RAM rows.
    Focal length equals image width, matching the tracker approximation. This is
    a distant environment approximation, not a reconstructed room or HDR probe.
    """
    s, t = np.meshgrid((np.arange(size, dtype=np.float32) + .5) * (2 / size) - 1,
                       (np.arange(size, dtype=np.float32) + .5) * (2 / size) - 1)
    one = np.ones_like(s)
    directions = np.stack([
        np.stack((one, -t, -s), -1), np.stack((-one, -t, s), -1),
        np.stack((s, one, t), -1), np.stack((s, -one, -t), -1),
        np.stack((s, -t, one), -1), np.stack((-s, -t, -one), -1),
    ])
    x, y, z = (directions[..., i] for i in range(3))
    forward = np.maximum(-y, 1e-6)
    u = .5 - x / forward
    v = .5 - z / forward * (rgb.shape[1] / rgb.shape[0])
    # Feather the observed patch into a dim neutral environment, avoiding a rectangular seam.
    weight = np.clip(np.minimum.reduce([u, 1-u, v, 1-v]) / .18, 0, 1)
    weight *= y < 0
    neutral = np.full(3, float(rgb.mean()) * .25, dtype=np.float32)
    cube = np.empty((6, size, size, 3), dtype=np.float32)
    for face in range(6):
        sampled = cv2.remap(rgb, (u[face] * (rgb.shape[1]-1)).astype(np.float32),
                            (v[face] * (rgb.shape[0]-1)).astype(np.float32),
                            cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        cube[face] = neutral + (sampled - neutral) * weight[face, ..., None]
    return cube


class WebcamEnvironment:
    """Reuse captured frames at 10 Hz, smoothing changes and fading stale input away."""

    def __init__(self, scene, model, config):
        self.config = config
        self.model = model
        self.enabled = True
        self._last_update = None
        self._smoothed = None
        self._lights = []
        for index, direction in enumerate(((-.45, 1, -.3), (.45, 1, -.3),
                                           (-.45, 1, .3), (.45, 1, .3))):
            light = DirectionalLight(f"webcam-fill-{index}")
            light.setDirection(Vec3(*direction))
            light.setColor((0, 0, 0, 1))
            node = scene.attachNewNode(light)
            scene.setLight(node)
            self._lights.append(light)
        self.texture = Texture("blurred-webcam-environment")
        self.texture.setupCubeMap(64, Texture.TUnsignedByte, Texture.FRgb)
        self.texture.setMinfilter(Texture.FTLinear)
        self.texture.setMagfilter(Texture.FTLinear)
        self.texture.setRamImage(bytes(6 * 64 * 64 * 3))
        self.stage = TextureStage("webcam-reflection")
        self.stage.setMode(TextureStage.MAdd)
        self.stage.setSort(10)
        self.set_enabled(True)

    def set_enabled(self, enabled):
        """Toggle both contributions for an immediate comparison with the base scene."""
        self.enabled = enabled
        if enabled:
            self.model.setTexture(self.stage, self.texture, 1)
            self.model.setTexGen(self.stage, TexGenAttrib.MWorldCubeMap)
        else:
            self.model.clearTexture(self.stage)
            self.model.clearTexGen(self.stage)
            for light in self._lights:
                light.setColor((0, 0, 0, 1))

    def update(self, frame_bgr, timestamp):
        """Smooth ambient color and reflected detail without saving webcam images."""
        if self._last_update is not None and timestamp - self._last_update < .1:
            return
        dt = .1 if self._last_update is None else max(0, timestamp - self._last_update)
        self._last_update = timestamp
        if frame_bgr is None:
            if self._smoothed is None:
                return
            target = np.zeros_like(self._smoothed)
        else:
            target = prepare_frame(frame_bgr)
        if self._smoothed is None or self._smoothed.shape != target.shape:
            self._smoothed = np.zeros_like(target)
        alpha = 1 - math.exp(-dt / self.config.webcam_smoothing_seconds)
        self._smoothed += (target - self._smoothed) * alpha
        if not self.enabled:
            return
        h, w = self._smoothed.shape[:2]
        regions = (self._smoothed[:h//2, :w//2], self._smoothed[:h//2, w//2:],
                   self._smoothed[h//2:, :w//2], self._smoothed[h//2:, w//2:])
        for light, region in zip(self._lights, regions):
            color = region.mean(axis=(0, 1)) * self.config.webcam_light_strength
            light.setColor((*map(float, color), 1))
        cube = reflection_cube(self._smoothed)
        pixels = np.rint(np.clip(cube * self.config.webcam_reflection_strength, 0, 1) * 255)
        # Panda's RAM texture component order is BGR.
        self.texture.setRamImage(pixels[..., ::-1].astype(np.uint8).tobytes())
