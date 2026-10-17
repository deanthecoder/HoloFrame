"""Select a webcam and send its head pose and reflection image to Godot."""

import argparse
from dataclasses import replace
import json
import multiprocessing as mp
from pathlib import Path
from queue import Empty
import signal
import socket
import time

import cv2
from cv2_enumerate_cameras import enumerate_cameras
import numpy as np

from config import AppConfig
from head_pose_tracker import HeadPoseTracker


CAMERA_SETTINGS = Path(__file__).with_name(".holoframe-camera.json")
DISPLAY_PROFILE = Path(__file__).with_name("godot") / "display_profile.json"


def display_geometry():
    """Use the same physical aperture and bezel offset as the Godot renderer."""
    profile = json.loads(DISPLAY_PROFILE.read_text())
    config = replace(AppConfig(), screen_width_mm=profile["screen_width_mm"],
                     webcam_above_screen_mm=profile["webcam_above_screen_mm"])
    return config, profile["screen_height_mm"]


def camera_key(camera) -> str:
    """Prefer device identity over indices, which can change between sessions."""
    return f"{camera.backend}:{camera.path or camera.name}"


def ordered_cameras(cameras, remembered: str | None, explicit_index: int | None):
    """Try the previous successful device first, unless an index was requested."""
    if explicit_index is not None:
        # CAP_ANY encodes the backend into the hundreds of the OpenCV index.
        cameras = [camera for camera in cameras if camera.index % 100 == explicit_index]
    if not cameras:
        raise RuntimeError("No matching webcam is connected")
    return sorted(cameras, key=lambda camera: camera_key(camera) != remembered)


def track_camera(index: int, backend: int, events, stop) -> None:
    """Keep potentially blocking camera reads in a process the selector can stop."""
    config, screen_height_mm = display_geometry()
    capture = cv2.VideoCapture(index, backend)
    tracker = None
    pose_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    image_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        if not capture.isOpened():
            raise RuntimeError(f"Webcam index {index} is unavailable")
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)
        tracker = HeadPoseTracker(config, screen_height_mm)
        last_image = 0.0
        while not stop.is_set():
            ok, frame = capture.read()
            now = time.monotonic()
            if not ok or frame is None:
                raise RuntimeError("Webcam stopped producing frames")
            height, width = frame.shape[:2]
            intrinsics = np.array(
                [[width, 0, width / 2], [0, width, height / 2], [0, 0, 1]],
                dtype=np.float32,
            )
            estimate = tracker.process(frame, now, intrinsics, np.zeros((4, 1), np.float32))
            detected = estimate.detected and estimate.position_mm is not None
            events.put((now, detected))
            # Hold Godot's saved or last valid view while no face is visible.
            if detected:
                pose = {
                    "eye_mm": estimate.position_mm.tolist(),
                    "webcam_position_mm": [config.webcam_horizontal_offset_mm,
                                           screen_height_mm / 2 + config.webcam_above_screen_mm, 0],
                    "focal_uv": [float(intrinsics[0, 0] / width), float(intrinsics[1, 1] / height)],
                }
                pose_socket.sendto(json.dumps(pose).encode(), ("127.0.0.1", 55123))
            if now - last_image >= 0.1:
                small = cv2.resize(frame, (128, 72), interpolation=cv2.INTER_AREA)
                small = cv2.GaussianBlur(small, (0, 0), 2.0)
                encoded, jpg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if not encoded:
                    raise RuntimeError("Could not encode webcam image")
                image_socket.sendto(jpg.tobytes(), ("127.0.0.1", 55124))
                last_image = now
    except KeyboardInterrupt:
        pass
    except Exception as error:
        print(f"[HoloFrame] Camera {index}: {error}", flush=True)
    finally:
        if tracker is not None:
            tracker.close()
        capture.release()
        pose_socket.close()
        image_socket.close()


def use_camera(camera, allow_switch: bool, remember, context=None) -> None:
    """Switch after a second without a face, or when a camera stops responding."""
    context = context or mp.get_context("spawn")
    events = context.Queue()
    stop = context.Event()
    worker = context.Process(target=track_camera, args=(camera.index, camera.backend, events, stop))
    print(f"[HoloFrame] Trying {camera.name} (index {camera.index})", flush=True)
    worker.start()
    started = time.monotonic()
    last_frame = None
    last_face = None
    first_frame = None
    remembered = False
    try:
        while worker.is_alive():
            try:
                timestamp, detected = events.get(timeout=0.1)
                last_frame = timestamp
                if first_frame is None:
                    first_frame = timestamp
                if detected:
                    last_face = timestamp
                    if not remembered:
                        remember(camera_key(camera))
                        remembered = True
                        print(f"[HoloFrame] Using {camera.name}; choice saved", flush=True)
            except Empty:
                pass
            now = time.monotonic()
            if last_frame is None and now - started > 5.0:
                break
            if last_frame is not None and now - last_frame > 2.0:
                break
            if allow_switch and first_frame is not None and now - (last_face or first_frame) >= 1.0:
                break
    finally:
        stop.set()
        worker.join(timeout=0.4)
        if worker.is_alive():
            worker.terminate()
            worker.join()
        events.close()


def main() -> None:
    """Cycle connected cameras until one sees the viewer, remembering success."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera-index", type=int)
    args = parser.parse_args()
    remembered = json.loads(CAMERA_SETTINGS.read_text())["camera"] if CAMERA_SETTINGS.exists() else None
    cameras = ordered_cameras(enumerate_cameras(), remembered, args.camera_index)

    def stop_tracking(_signum, _frame) -> None:
        # Let the normal cleanup release the camera worker when Godot exits.
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_tracking)

    def remember(key: str) -> None:
        # Only a device identifier is saved, never webcam images.
        CAMERA_SETTINGS.write_text(json.dumps({"camera": key}))

    try:
        while True:
            for camera in cameras:
                use_camera(camera, len(cameras) > 1, remember)
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
