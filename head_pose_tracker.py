"""Head pose tracking pipeline built on MediaPipe FaceMesh and solvePnPRansac."""

from dataclasses import dataclass
from typing import Optional

import cv2
import mediapipe as mp
import numpy as np

from config import AppConfig
from one_euro import OneEuro


# Landmark indices chosen for pose stability (eyes, nose, mouth, cheeks)
LANDMARK_ORDER = (
    1,    # nose tip
    168,  # nose bridge
    199,  # chin
    33,   # left eye outer corner
    133,  # left eye inner corner
    159,  # left eye upper lid
    145,  # left eye lower lid
    362,  # right eye inner corner
    263,  # right eye outer corner
    386,  # right eye upper lid
    374,  # right eye lower lid
    61,   # mouth left corner
    291,  # mouth right corner
    13,   # mouth upper midpoint
    14,   # mouth lower midpoint
    234,  # left cheek
    454,  # right cheek
)

MODEL_POINTS = np.array([
    [0.0, 0.0, 0.0],
    [0.0, 120.0, -20.0],
    [0.0, -330.0, -65.0],
    [-225.0, 170.0, -135.0],
    [-100.0, 170.0, -125.0],
    [-160.0, 210.0, -120.0],
    [-160.0, 140.0, -120.0],
    [100.0, 170.0, -125.0],
    [225.0, 170.0, -135.0],
    [160.0, 210.0, -120.0],
    [160.0, 140.0, -120.0],
    [-150.0, -150.0, -125.0],
    [150.0, -150.0, -125.0],
    [0.0, -100.0, -110.0],
    [0.0, -190.0, -110.0],
    [-320.0, 50.0, -50.0],
    [320.0, 50.0, -50.0],
], dtype=np.float32)


@dataclass
class HeadPoseEstimate:
    detected: bool
    position_mm: Optional[np.ndarray]


class HeadPoseTracker:
    def __init__(self, config: AppConfig):
        self._config = config
        self._face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._smooth = {
            axis: OneEuro(
                config.smoothing_min_cutoff,
                config.smoothing_beta,
                config.smoothing_dcutoff,
            )
            for axis in ("x", "y", "z")
        }
        self._had_face = False

    def process(self, frame_bgr, timestamp, camera_matrix, dist_coeffs) -> HeadPoseEstimate:
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        res = self._face_mesh.process(rgb)

        if not res.multi_face_landmarks:
            self._had_face = False
            return HeadPoseEstimate(False, None)

        lm2d = res.multi_face_landmarks[0].landmark
        img_pts = np.array(
            [[lm2d[idx].x * w, lm2d[idx].y * h] for idx in LANDMARK_ORDER],
            dtype=np.float32,
        )

        ok_pnp, rvec, tvec, inliers = cv2.solvePnPRansac(
            MODEL_POINTS,
            img_pts,
            camera_matrix,
            dist_coeffs,
            iterationsCount=100,
            reprojectionError=8.0,
            confidence=0.99,
            flags=cv2.SOLVEPNP_EPNP,
        )

        if not ok_pnp or inliers is None or len(inliers) < 6:
            self._had_face = False
            return HeadPoseEstimate(False, None)

        raw = np.array([
            float(tvec[0, 0]),
            float(tvec[1, 0]),
            float(tvec[2, 0]),
        ], dtype=np.float32)
        scaled = raw * self._config.translation_scale

        if not self._had_face:
            for axis, value in zip(("x", "y", "z"), scaled):
                self._smooth[axis].reset(value, timestamp)
            self._had_face = True

        filtered = np.array([
            self._smooth["x"].filter(scaled[0], timestamp),
            self._smooth["y"].filter(scaled[1], timestamp),
            self._smooth["z"].filter(scaled[2], timestamp),
        ], dtype=np.float32)

        return HeadPoseEstimate(True, filtered)

    def close(self) -> None:
        self._face_mesh.close()


__all__ = ["HeadPoseTracker", "HeadPoseEstimate", "LANDMARK_ORDER", "MODEL_POINTS"]
