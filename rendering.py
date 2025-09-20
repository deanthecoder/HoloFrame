"""Rendering helpers for the virtual scene."""

import numpy as np
import cv2

from config import AppConfig
from pose_utils import build_view_rotation


CUBE_EDGES = (
    (0, 1), (1, 2), (2, 3), (3, 0),
    (4, 5), (5, 6), (6, 7), (7, 4),
    (0, 4), (1, 5), (2, 6), (3, 7),
)


class CubeRenderer:
    def __init__(self, config: AppConfig):
        half = config.cube_size_mm / 2.0
        center = np.array([0.0, 0.0, config.cube_distance_mm], dtype=np.float32)
        self._points = (np.float32([
            [-half, -half, -half],
            [half, -half, -half],
            [half, half, -half],
            [-half, half, -half],
            [-half, -half, half],
            [half, -half, half],
            [half, half, half],
            [-half, half, half],
        ]) + center)
        self._center = center

    def draw(self, canvas, camera_pos_mm, camera_matrix, dist_coeffs):
        cam_pos = camera_pos_mm.astype(np.float32)
        view_R = build_view_rotation(cam_pos, self._center)
        view_t = (-view_R @ cam_pos).reshape(3, 1)
        view_rvec, _ = cv2.Rodrigues(view_R)

        cube_img, _ = cv2.projectPoints(self._points, view_rvec, view_t, camera_matrix, dist_coeffs)
        cube_pixels = np.rint(cube_img.reshape(-1, 2)).astype(int)

        for idx0, idx1 in CUBE_EDGES:
            p0 = tuple(cube_pixels[idx0])
            p1 = tuple(cube_pixels[idx1])
            cv2.line(canvas, p0, p1, (120, 200, 255), 2)

        for pt in cube_pixels:
            cv2.circle(canvas, tuple(pt), 3, (200, 200, 200), -1)


__all__ = ["CubeRenderer"]
