"""Utility math helpers for head-pose calculations."""

import math
import numpy as np
import cv2


def rotation_vector_to_ypr(rvec):
    """Return yaw/pitch/roll (degrees) for an OpenCV Rodrigues rotation vector."""
    R, _ = cv2.Rodrigues(rvec)
    sy = math.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2)
    singular = sy < 1e-6
    if not singular:
        yaw = math.degrees(math.atan2(R[2, 0], R[2, 2]))
        pitch = math.degrees(math.atan2(-R[2, 1], sy))
        roll = math.degrees(math.atan2(R[1, 0], R[0, 0]))
    else:
        yaw = math.degrees(math.atan2(-R[0, 2], R[0, 0]))
        pitch = math.degrees(math.atan2(-R[2, 1], sy))
        roll = 0.0
    return yaw, pitch, roll


def build_view_rotation(cam_pos, target, world_down=np.array([0.0, 1.0, 0.0], dtype=np.float32)):
    """Build a rotation matrix that points the camera at `target` while keeping +Y down."""
    world_down = world_down.astype(np.float32)
    wd_norm = np.linalg.norm(world_down)
    if wd_norm > 1e-6:
        world_down = world_down / wd_norm
    world_down_orig = world_down.copy()

    forward = target.astype(np.float32) - cam_pos.astype(np.float32)
    norm = np.linalg.norm(forward)
    if norm < 1e-6:
        forward = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    else:
        forward /= norm

    right = np.cross(world_down, forward)
    right_norm = np.linalg.norm(right)
    if right_norm < 1e-6:
        alt_down = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        right = np.cross(alt_down, forward)
        right_norm = np.linalg.norm(right)
    if right_norm < 1e-6:
        right = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    else:
        right /= right_norm

    down = np.cross(forward, right)
    down_norm = np.linalg.norm(down)
    if down_norm < 1e-6:
        down = world_down_orig
    else:
        down /= down_norm

    R = np.stack([right, down, forward], axis=0).astype(np.float32)
    return R


__all__ = ["rotation_vector_to_ypr", "build_view_rotation"]
