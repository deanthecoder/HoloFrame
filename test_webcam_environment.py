"""Check lighting direction, reflection coverage, smoothing, and loss of camera input."""

import unittest

# Maintain the application's Windows native-library import order.
import HoloFrame
import numpy as np
from panda3d.core import NodePath
from config import AppConfig
from webcam_environment import WebcamEnvironment, prepare_frame, reflection_cube


class WebcamEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.scene = NodePath('scene')
        self.model = self.scene.attachNewNode('model')
        self.environment = WebcamEnvironment(self.scene, self.model, AppConfig())

    def test_bgr_is_converted_to_linear_rgb(self):
        red = np.full((36, 64, 3), (0, 0, 255), np.uint8)
        rgb = prepare_frame(red)
        np.testing.assert_allclose(rgb[18, 32], [1, 0, 0], atol=1e-6)

    def test_camera_image_only_covers_front_facing_directions(self):
        rgb = np.zeros((36, 64, 3), np.float32)
        rgb[:, :, 0] = 1
        cube = reflection_cube(rgb)
        self.assertGreater(cube[3, 32, 32, 0], .9)  # -Y, towards the viewer
        self.assertLess(cube[2, 32, 32, 0], .1)  # +Y remains neutral
        np.testing.assert_allclose(cube[2, 32, 32, 0], cube[2, 32, 32, 1])

    def test_image_left_reflects_from_world_right(self):
        rgb = np.zeros((36, 64, 3), np.float32)
        rgb[:, :32, 0] = 1
        cube = reflection_cube(rgb)
        # -Y face's positive-X samples are on its right side.
        self.assertGreater(cube[3, 32, 39, 0], cube[3, 32, 24, 0])

    def test_smoothing_throttle_and_camera_failure_fade(self):
        bright = np.full((36, 64, 3), 255, np.uint8)
        env = self.environment
        env.update(bright, 0)
        first = float(env._smoothed.mean())
        self.assertGreater(first, 0)
        self.assertLess(first, .2)
        env.update(bright, .05)
        self.assertAlmostEqual(float(env._smoothed.mean()), first)
        env.update(bright, 1)
        self.assertGreater(float(env._smoothed.mean()), first)
        env.update(None, 6)
        self.assertLess(float(env._smoothed.mean()), .01)
        self.assertEqual(len(env.texture.getRamImage()), 6 * 64 * 64 * 3)

    def test_toggle_removes_both_contributions(self):
        env = self.environment
        env.update(np.full((36, 64, 3), 255, np.uint8), 0)
        self.assertTrue(self.model.hasTexture())
        env.set_enabled(False)
        self.assertFalse(self.model.hasTexture())
        for light in env._lights:
            self.assertEqual(tuple(light.getColor())[:3], (0, 0, 0))
        env.set_enabled(True)
        self.assertTrue(self.model.hasTexture())


if __name__ == '__main__':
    unittest.main()
