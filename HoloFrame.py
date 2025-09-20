# Setup:
#   python -m pip install --upgrade pip
#   pip install opencv-python mediapipe numpy pygame

import cv2
import numpy as np
import time
import math
import pygame

from config import AppConfig
from head_pose_tracker import HeadPoseTracker
from rendering import CubeRenderer


# ---------- Main ----------
def main():
    config = AppConfig()

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise RuntimeError("Webcam not found")

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)

    pygame.init()
    pygame.display.set_caption("HoloFrame (ESC to quit)")
    display_info = pygame.display.Info()
    win_w, win_h = display_info.current_w, display_info.current_h
    if win_w <= 0 or win_h <= 0:
        win_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
        win_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
    screen = pygame.display.set_mode((win_w, win_h), pygame.FULLSCREEN)

    cap_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
    cap_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 360
    scale = min(win_w / max(1, cap_w), win_h / max(1, cap_h))
    if scale <= 0:
        scale = 1.0
    disp_w = max(1, min(win_w, int(round(cap_w * scale))))
    disp_h = max(1, min(win_h, int(round(cap_h * scale))))
    frame_surface = pygame.Surface((disp_w, disp_h))

    tracker = HeadPoseTracker(config)
    cube_renderer = CubeRenderer(config)

    default_cam_pos = np.array(config.default_camera_pos_mm, dtype=np.float32)
    cam_pos_display = default_cam_pos.copy()
    fps_avg = None
    t_prev = time.time()
    motion_t_prev = t_prev

    running = True
    while running:
        ok, frame = cap.read()
        if not ok:
            break

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
        if not running:
            break

        h, w = frame.shape[:2]
        canvas = np.zeros((h, w, 3), dtype=np.uint8)
        canvas[:] = (10, 10, 20)

        frame_time = time.time()
        dt_motion = max(0.0, frame_time - motion_t_prev)

        focal = w
        K = np.array([[focal, 0.0, w / 2.0],
                      [0.0, focal, h / 2.0],
                      [0.0, 0.0, 1.0]], dtype=np.float32)
        dist = np.zeros((4, 1), dtype=np.float32)

        estimate = tracker.process(frame, frame_time, K, dist)

        if estimate.detected and estimate.position_mm is not None:
            cam_pos_display = estimate.position_mm.astype(np.float32)
            pose_text = (
                f"x={cam_pos_display[0]:+.1f}  "
                f"y={cam_pos_display[1]:+.1f}  "
                f"z={cam_pos_display[2]:+.1f}"
            )
        else:
            pose_text = "No face"
            lerp = 1.0 - math.exp(-config.recenter_lerp_rate * dt_motion)
            lerp = float(min(max(lerp, 0.0), 1.0))
            cam_pos_display = cam_pos_display + (default_cam_pos - cam_pos_display) * lerp
            cam_pos_display = cam_pos_display.astype(np.float32)

        cube_renderer.draw(canvas, cam_pos_display, K, dist)
        motion_t_prev = frame_time

        t_now = time.time()
        fps = 1.0 / max(1e-6, (t_now - t_prev))
        t_prev = t_now
        fps_avg = fps if fps_avg is None else (fps_avg * 0.9 + fps * 0.1)

        cv2.putText(canvas, pose_text, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (240, 240, 240), 2, cv2.LINE_AA)
        cv2.putText(canvas, f"FPS: {fps_avg:.1f}", (10, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 255), 2, cv2.LINE_AA)

        display = cv2.resize(canvas, (disp_w, disp_h), interpolation=cv2.INTER_LINEAR)
        display_rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
        surface_array = np.transpose(display_rgb, (1, 0, 2)).copy()
        pygame.surfarray.blit_array(frame_surface, surface_array)
        screen.fill((0, 0, 0))
        offset_x = (win_w - disp_w) // 2
        offset_y = (win_h - disp_h) // 2
        screen.blit(frame_surface, (offset_x, offset_y))
        pygame.display.flip()

    tracker.close()
    cap.release()
    pygame.quit()

if __name__ == "__main__":
    main()
