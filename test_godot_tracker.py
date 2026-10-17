"""Check camera selection, stalled devices, and loss of face tracking."""

from queue import Empty
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from godot_tracker import camera_key, display_geometry, ordered_cameras, track_camera, use_camera


def camera(index, path):
    return SimpleNamespace(index=index, backend=0, path=path, name=path)


class CameraSelectionTests(unittest.TestCase):
    def test_display_profile_matches_macbook_fullscreen_aperture(self):
        config, height = display_geometry()
        self.assertEqual(config.screen_width_mm, 302.4)
        self.assertEqual(height, 189.8)
        self.assertAlmostEqual(height / 2 + config.webcam_above_screen_mm, 98.2)

    def test_remembers_device_when_indices_change(self):
        phone, builtin = camera(1200, "phone"), camera(1201, "builtin")
        remembered = camera_key(builtin)
        phone.index, builtin.index = 1201, 1200
        self.assertEqual(ordered_cameras([phone, builtin], remembered, None), [builtin, phone])

    def test_manual_index_overrides_remembered_choice(self):
        phone, builtin = camera(1200, "phone"), camera(1201, "builtin")
        self.assertEqual(ordered_cameras([phone, builtin], camera_key(phone), 1), [builtin])

    def context(self, events):
        context = Mock()
        context.Queue.return_value.get.side_effect = events
        context.Process.return_value.is_alive.return_value = True
        return context

    def test_switches_after_one_second_without_face(self):
        context = self.context([(0.1, False), (1.2, False)])
        remember = Mock()
        with patch("godot_tracker.time.monotonic", side_effect=[0, 0.1, 1.2]):
            use_camera(camera(0, "phone"), True, remember, context)
        remember.assert_not_called()
        context.Process.return_value.terminate.assert_called_once()

    def test_success_is_saved_once_then_switches_when_face_is_lost(self):
        context = self.context([(0.1, True), (0.6, True), (1.8, False)])
        remember = Mock()
        device = camera(1, "builtin")
        with patch("godot_tracker.time.monotonic", side_effect=[0, 0.1, 0.6, 1.8]):
            use_camera(device, True, remember, context)
        remember.assert_called_once_with(camera_key(device))

    def test_single_camera_waits_for_face_without_reopening(self):
        context = self.context([(0.1, False), (1.2, False), (1.5, True)])
        context.Process.return_value.is_alive.side_effect = [True, True, True, False, False]
        remember = Mock()
        with patch("godot_tracker.time.monotonic", side_effect=[0, 0.1, 1.2, 1.5]):
            use_camera(camera(0, "builtin"), False, remember, context)
        remember.assert_called_once()
        context.Process.return_value.terminate.assert_not_called()

    def test_camera_with_blocked_read_is_stopped(self):
        context = self.context([Empty])
        with patch("godot_tracker.time.monotonic", side_effect=[0, 6]):
            use_camera(camera(0, "phone"), True, Mock(), context)
        context.Process.return_value.terminate.assert_called_once()

    def test_missing_face_does_not_send_default_pose(self):
        capture = Mock()
        capture.read.return_value = (True, np.zeros((16, 16, 3), dtype=np.uint8))
        tracker = Mock()
        tracker.process.side_effect = [
            SimpleNamespace(detected=False, position_mm=None),
            SimpleNamespace(detected=True, position_mm=np.array([20, 140, 600])),
        ]
        stop = Mock()
        stop.is_set.side_effect = [False, False, True]
        pose_socket, image_socket = Mock(), Mock()
        with patch("godot_tracker.cv2.VideoCapture", return_value=capture), \
                patch("godot_tracker.HeadPoseTracker", return_value=tracker), \
                patch("godot_tracker.socket.socket", side_effect=[pose_socket, image_socket]):
            track_camera(0, 0, Mock(), stop)
        pose_socket.sendto.assert_called_once()
        packet, address = pose_socket.sendto.call_args.args
        pose = json.loads(packet)
        self.assertEqual(pose["eye_mm"], [20, 140, 600])
        self.assertEqual(pose["webcam_position_mm"], [0, 98.2, 0])
        self.assertEqual(pose["focal_uv"], [1, 1])
        self.assertEqual(address, ("127.0.0.1", 55123))
        capture.release.assert_called_once()


if __name__ == "__main__":
    unittest.main()
