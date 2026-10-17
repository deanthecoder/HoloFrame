"""Recover a known eye position through the shared face-tracking pipeline."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from config import AppConfig
from head_pose_tracker import HeadPoseTracker, LANDMARK_ORDER, MODEL_POINTS


class TrackingTests(unittest.TestCase):
    def test_synthetic_face_recovers_eye_position(self):
        config = AppConfig()
        height = 189.8
        intrinsics = np.array([[640., 0, 320], [0, 640, 180], [0, 0, 1]])
        rotation = np.array([3.0, .15, -.1])
        translation = np.array([80., -40., 4000.])
        pixels, _ = cv2.projectPoints(MODEL_POINTS, rotation, translation, intrinsics, None)
        landmarks = [SimpleNamespace(x=0., y=0.) for _ in range(468)]
        for index, pixel in zip(LANDMARK_ORDER, pixels.reshape(-1, 2)):
            landmarks[index] = SimpleNamespace(x=pixel[0] / 640, y=pixel[1] / 360)
        face_mesh = Mock()
        face_mesh.process.return_value = SimpleNamespace(
            multi_face_landmarks=[SimpleNamespace(landmark=landmarks)])
        with patch('head_pose_tracker.mp.solutions.face_mesh.FaceMesh', return_value=face_mesh):
            tracker = HeadPoseTracker(config, height)
        try:
            estimate = tracker.process(np.zeros((360, 640, 3), np.uint8), 1., intrinsics, None)
            self.assertTrue(estimate.detected)
            eye = (cv2.Rodrigues(rotation)[0] @ MODEL_POINTS[[3, 4, 7, 8]].mean(axis=0)
                   + translation) * config.translation_scale
            webcam_height = height / 2 + config.webcam_above_screen_mm
            np.testing.assert_allclose(estimate.position_mm,
                                       [-eye[0], webcam_height-eye[1], eye[2]], atol=.1)
            tracker.mark_lost()
            self.assertFalse(tracker._had_face)
        finally:
            tracker.close()


if __name__ == '__main__':
    unittest.main()
