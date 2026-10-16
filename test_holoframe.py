"""Focused checks for the fixed screen, display selection, and tracking failure paths."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

# Import the application first to exercise its native-library startup order.
from HoloFrame import HoloFrameApp
from config import AppConfig
from display_selection import Display, select_display
from head_pose_tracker import HeadPoseTracker, MODEL_POINTS
from projection import apply_screen_projection

import cv2
import numpy as np
from panda3d.core import NodePath, PerspectiveLens, Point2, Point3


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.camera = NodePath("camera")
        self.lens = PerspectiveLens()

    def project(self, eye, point):
        apply_screen_projection(self.camera, self.lens, eye, 344, 215)
        result = Point2()
        self.lens.project(Point3(*point) - self.camera.getPos(), result)
        return result

    def test_screen_plane_stays_fixed_for_all_eye_positions(self):
        for eye in [(0, 0, 600), (100, 50, 400), (-100, -30, 800)]:
            for x, z in [(-1, 1), (1, 1), (-1, -1), (1, -1), (0, 0)]:
                with self.subTest(eye=eye, corner=(x, z)):
                    result = self.project(eye, (x * .172, 0, z * .1075))
                    self.assertAlmostEqual(result.x, x, places=5)
                    self.assertAlmostEqual(result.y, z, places=5)
                    self.assertEqual(self.camera.getHpr(), (0, 0, 0))

    def test_parallax_depends_on_depth(self):
        screen = self.project((100, 0, 600), (0, 0, 0)).x
        shallow = self.project((100, 0, 600), (0, .1, 0)).x
        deep = self.project((100, 0, 600), (0, .5, 0)).x
        self.assertAlmostEqual(screen, 0, places=5)
        self.assertGreater(shallow, screen)
        self.assertGreater(deep, shallow)

    def test_moving_closer_reveals_more_world(self):
        # A fixed point behind the screen moves nearer the image center as we approach.
        far = self.project((0, 0, 800), (.1, .4, 0)).x
        near = self.project((0, 0, 400), (.1, .4, 0)).x
        self.assertLess(near, far)


class DisplayTests(unittest.TestCase):
    def setUp(self):
        self.external = Display(0, 0, 3440, 1440)
        self.laptop = Display(-1920, 921, 1920, 1200, True)

    def test_internal_panel_wins_over_primary(self):
        self.assertEqual(select_display([self.external, self.laptop]), self.laptop)

    def test_override_wins_over_internal(self):
        self.assertEqual(select_display([self.external, self.laptop], 0), self.external)

    def test_primary_fallback(self):
        self.assertEqual(select_display([Display(-1280, 0, 1280, 1024), self.external]),
                         self.external)

    def test_missing_and_invalid_displays(self):
        self.assertIsNone(select_display([]))
        with self.assertRaises(ValueError):
            select_display([self.external], -1)


class TrackingTests(unittest.TestCase):
    def test_camera_failure_recenters_and_updates_status(self):
        app = SimpleNamespace(
            cap=Mock(), tracker=Mock(), app_config=AppConfig(),
            motion_t_prev=10.0, t_prev=10.0, fps_avg=None,
            cam_pos_display=np.array([100., 50., 400.], dtype=np.float32),
            default_cam_pos=np.array([0., 0., 600.], dtype=np.float32),
            pose_text=Mock(), fps_text=Mock(), room_text=Mock(), _apply_camera_pose=Mock(),
            room_width=.344, room_height=.215, room_depth=.45,
            _room_min_width=.1, _room_min_height=.1, _room_min_depth=.3)
        app.cap.read.return_value = (False, None)
        before = np.linalg.norm(app.cam_pos_display - app.default_cam_pos)
        with patch('HoloFrame.time.perf_counter', return_value=11.0):
            HoloFrameApp._update_task(app, None)
        self.assertLess(np.linalg.norm(app.cam_pos_display - app.default_cam_pos), before)
        app.pose_text.setText.assert_called_once_with('Camera unavailable')
        app.tracker.mark_lost.assert_called_once()
        app.tracker.process.assert_not_called()
        app._apply_camera_pose.assert_called_once()
        self.assertEqual(app.motion_t_prev, 11.0)

    def test_synthetic_face_recovers_eye_position(self):
        # Project a known rotated face, then solve it through the actual RANSAC pipeline.
        from head_pose_tracker import LANDMARK_ORDER
        config = AppConfig()
        K = np.array([[640., 0, 320], [0, 640, 180], [0, 0, 1]])
        rvec = np.array([3.0, .15, -.1])
        tvec = np.array([80., -40., 4000.])
        pixels, _ = cv2.projectPoints(MODEL_POINTS, rvec, tvec, K, None)
        landmarks = [SimpleNamespace(x=0., y=0.) for _ in range(468)]
        for index, pixel in zip(LANDMARK_ORDER, pixels.reshape(-1, 2)):
            landmarks[index] = SimpleNamespace(x=pixel[0] / 640, y=pixel[1] / 360)
        face_mesh = Mock()
        face_mesh.process.return_value = SimpleNamespace(
            multi_face_landmarks=[SimpleNamespace(landmark=landmarks)])
        with patch('head_pose_tracker.mp.solutions.face_mesh.FaceMesh', return_value=face_mesh):
            tracker = HeadPoseTracker(config, 215)
        estimate = tracker.process(np.zeros((360, 640, 3), np.uint8), 1., K, None)
        self.assertTrue(estimate.detected)
        eye = (cv2.Rodrigues(rvec)[0] @ MODEL_POINTS[[3, 4, 7, 8]].mean(axis=0) + tvec) * .125
        np.testing.assert_allclose(estimate.position_mm, [-eye[0], 115.5-eye[1], eye[2]], atol=.1)
        tracker.mark_lost()
        self.assertFalse(tracker._had_face)
        tracker.close()


if __name__ == '__main__':
    unittest.main()
