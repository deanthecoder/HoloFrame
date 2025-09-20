# Setup:
#   python -m pip install --upgrade pip
#   pip install opencv-python mediapipe numpy pygame

import cv2
import numpy as np
import time
import math
import mediapipe as mp
import pygame

# ---------- 1-Euro filter (per-signal smoothing; low lag) ----------
class OneEuro:
    def __init__(self, min_cutoff=1.0, beta=0.02, dcutoff=1.0):
        self.min_cutoff, self.beta, self.dcutoff = min_cutoff, beta, dcutoff
        self.t_prev = None
        self.x_prev = None
        self.dx_prev = 0.0

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def filter(self, x, t):
        if self.t_prev is None:
            self.t_prev, self.x_prev = t, x
            return x
        dt = max(1e-6, t - self.t_prev)
        self.t_prev = t
        dx = (x - self.x_prev) / dt
        a_d = self._alpha(self.dcutoff, dt)
        dx_hat = a_d * dx + (1 - a_d) * self.dx_prev
        self.dx_prev = dx_hat
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = self._alpha(cutoff, dt)
        x_hat = a * x + (1 - a) * self.x_prev
        self.x_prev = x_hat
        return x_hat

# ---------- Pose helpers ----------
def rvec_tvec_to_ypr(rvec):
    R, _ = cv2.Rodrigues(rvec)
    # OpenCV camera coords: +X right, +Y down, +Z forward
    sy = math.sqrt(R[0,0]**2 + R[1,0]**2)
    singular = sy < 1e-6
    if not singular:
        yaw   = math.degrees(math.atan2(R[2,0], R[2,2]))   # Y
        pitch = math.degrees(math.atan2(-R[2,1], sy))      # X
        roll  = math.degrees(math.atan2(R[1,0], R[0,0]))   # Z
    else:
        yaw   = math.degrees(math.atan2(-R[0,2], R[0,0]))
        pitch = math.degrees(math.atan2(-R[2,1], sy))
        roll  = 0.0
    return yaw, pitch, roll

def build_view_rotation(cam_pos, target, world_down=np.array([0.0, 1.0, 0.0], dtype=np.float32)):
    """Creates a rotation matrix that points the camera at the target while keeping +Y down in image space."""
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

# Indices for MediaPipe FaceMesh (468 pts)
# Common stable points: nose tip, chin, eye corners, mouth corners
LANDMARK_ORDER = [
    ("nose_tip", 1),
    ("chin", 199),
    ("left_eye_outer", 33),
    ("right_eye_outer", 263),
    ("left_mouth", 61),
    ("right_mouth", 291),
]

# Approximate 3D model coordinates (mm) for the chosen fiducials.
MODEL_POINTS = np.array([
    [0.0, 0.0, 0.0],             # nose tip
    [0.0, -330.0, -65.0],        # chin
    [-225.0, 170.0, -135.0],     # left eye outer corner
    [225.0, 170.0, -135.0],      # right eye outer corner
    [-150.0, -150.0, -125.0],    # left mouth corner
    [150.0, -150.0, -125.0],     # right mouth corner
], dtype=np.float32)

FACIAL_IDXS = dict(LANDMARK_ORDER)

# Simple cube parameters (world space in millimetres; treat the cube centre as the world origin).
CUBE_SIZE = 1000.0
CUBE_DISTANCE = 0.0  # place the cube centre roughly 6 m in front of the real camera
CUBE_HALF = CUBE_SIZE / 2.0
CUBE_CENTER = np.array([0.0, 0.0, CUBE_DISTANCE], dtype=np.float32)
CUBE_POINTS = (np.float32([
    [-CUBE_HALF, -CUBE_HALF, -CUBE_HALF],
    [ CUBE_HALF, -CUBE_HALF, -CUBE_HALF],
    [ CUBE_HALF,  CUBE_HALF, -CUBE_HALF],
    [-CUBE_HALF,  CUBE_HALF, -CUBE_HALF],
    [-CUBE_HALF, -CUBE_HALF,  CUBE_HALF],
    [ CUBE_HALF, -CUBE_HALF,  CUBE_HALF],
    [ CUBE_HALF,  CUBE_HALF,  CUBE_HALF],
    [-CUBE_HALF,  CUBE_HALF,  CUBE_HALF],
]) + CUBE_CENTER)
CUBE_EDGES = [
    (0, 1), (1, 2), (2, 3), (3, 0),
    (4, 5), (5, 6), (6, 7), (7, 4),
    (0, 4), (1, 5), (2, 6), (3, 7),
]

# --- Display helpers ---

def resize_cover(img, dst_w, dst_h):
    """Resize an image to completely fill (dst_w, dst_h) without distortion.
    Preserves aspect ratio by scaling to cover and then center-cropping.
    """
    h, w = img.shape[:2]
    if w <= 0 or h <= 0 or dst_w <= 0 or dst_h <= 0:
        return img
    scale = max(dst_w / w, dst_h / h)
    new_w, new_h = int(round(w * scale)), int(round(h * scale))
    img2 = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    x0 = max(0, (new_w - dst_w) // 2)
    y0 = max(0, (new_h - dst_h) // 2)
    return img2[y0:y0+dst_h, x0:x0+dst_w]

# ---------- Main ----------
def main():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise RuntimeError("Webcam not found")

    # Request a lower capture resolution to save work on lower-power devices.
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)

    mp_face = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=False,
        max_num_faces=1,
        refine_landmarks=True,    # iris mesh; helps stability a bit
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5
    )

    window_name = "Head Pose (ESC to quit)"
    pygame.init()
    pygame.display.set_caption(window_name)
    display_info = pygame.display.Info()
    win_w, win_h = display_info.current_w, display_info.current_h
    if win_w <= 0 or win_h <= 0:
        # Fallback to capture size if display info is unavailable
        win_w, win_h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if win_w <= 0 or win_h <= 0:
            win_w, win_h = 640, 480
    screen = pygame.display.set_mode((win_w, win_h), pygame.FULLSCREEN)
    cap_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
    cap_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 360
    scale = min(win_w / max(1, cap_w), win_h / max(1, cap_h))
    if scale <= 0:
        scale = 1.0
    disp_w = max(1, min(win_w, int(round(cap_w * scale))))
    disp_h = max(1, min(win_h, int(round(cap_h * scale))))
    frame_surface = pygame.Surface((disp_w, disp_h))

    # Smoothers for each DOF
    smooth = {k: OneEuro(0.1, 0.01, 1.0) for k in ["x", "y", "z"]}

    fps_avg = None
    t_prev = time.time()

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
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = mp_face.process(rgb)

        pose_text = "No face"
        if res.multi_face_landmarks:
            lm2d = res.multi_face_landmarks[0].landmark

            # Build 2D-3D correspondences from the chosen indices
            img_pts = np.array(
                [[lm2d[idx].x * w, lm2d[idx].y * h] for _, idx in LANDMARK_ORDER],
                dtype=np.float32,
            )
            obj_pts = MODEL_POINTS

            # Camera intrinsics (simple guess; good enough to start)
            f = w  # focal length ~ width in pixels
            K = np.array([[f, 0, w/2],
                          [0, f, h/2],
                          [0, 0, 1]], dtype=np.float32)
            dist = np.zeros((4, 1), dtype=np.float32)

            ok_pnp, rvec, tvec = cv2.solvePnP(
                obj_pts, img_pts, K, dist, flags=cv2.SOLVEPNP_ITERATIVE
            )

            if ok_pnp:
                t_now = time.time()
                x = float(smooth["x"].filter(tvec[0,0], t_now))
                y = -float(smooth["y"].filter(tvec[1,0], t_now))
                z = float(smooth["z"].filter(tvec[2,0], t_now))
                pose_text = f"x={x:+.1f}  y={y:+.1f}  z={z:+.1f}"

                # Render the virtual cube using a look-at camera that always targets the cube centre
                cam_pos = np.array([x, -y, z], dtype=np.float32)
                view_R = build_view_rotation(cam_pos, CUBE_CENTER)
                view_t = -view_R @ cam_pos
                view_rvec, _ = cv2.Rodrigues(view_R)

                view_rvec = view_rvec.astype(np.float32)
                view_t = view_t.astype(np.float32).reshape(3, 1)

                cube_img, _ = cv2.projectPoints(CUBE_POINTS, view_rvec, view_t, K, dist)
                cube_pixels = np.rint(cube_img.reshape(-1, 2)).astype(int)

                for idx0, idx1 in CUBE_EDGES:
                    p0 = tuple(cube_pixels[idx0])
                    p1 = tuple(cube_pixels[idx1])
                    cv2.line(canvas, p0, p1, (120, 200, 255), 2)

                for pt in cube_pixels:
                    cv2.circle(canvas, tuple(pt), 3, (200, 200, 200), -1)

        # FPS
        t_now = time.time()
        fps = 1.0 / max(1e-6, (t_now - t_prev))
        t_prev = t_now
        fps_avg = fps if fps_avg is None else (fps_avg*0.9 + fps*0.1)

        # HUD
        cv2.putText(canvas, pose_text, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (240,240,240), 2, cv2.LINE_AA)
        cv2.putText(canvas, f"FPS: {fps_avg:.1f}", (10, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200,200,255), 2, cv2.LINE_AA)

        # Resize the final canvas to a fixed-width presentation frame.
        display = cv2.resize(canvas, (disp_w, disp_h), interpolation=cv2.INTER_LINEAR)

        # Display the frame in the fullscreen SDL window (pygame handles the swap).
        display_rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
        surface_array = np.transpose(display_rgb, (1, 0, 2)).copy()
        pygame.surfarray.blit_array(frame_surface, surface_array)
        screen.fill((0, 0, 0))
        offset_x = (win_w - disp_w) // 2
        offset_y = (win_h - disp_h) // 2
        screen.blit(frame_surface, (offset_x, offset_y))
        pygame.display.flip()

    mp_face.close()
    cap.release()
    pygame.quit()

if __name__ == "__main__":
    main()
