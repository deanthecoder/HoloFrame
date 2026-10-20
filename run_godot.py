"""Launch either scene and its webcam tracker on Windows, macOS, or Linux."""

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    scene = parser.add_mutually_exclusive_group()
    scene.add_argument("--gallery", action="store_true")
    scene.add_argument("--cornell", action="store_true")
    parser.add_argument("--photo", action="append", type=Path, default=[])
    parser.add_argument("--camera-index", type=int)
    parser.add_argument("--reset-camera", action="store_true")
    parser.add_argument("--godot", default=os.environ.get("GODOT_EXE"),
                        help="Godot executable path (or set GODOT_EXE)")
    args = parser.parse_args()
    if len(args.photo) > 3:
        parser.error("Expected up to three --photo paths")
    if args.cornell and args.photo:
        parser.error("--photo cannot be combined with --cornell")
    executable = args.godot or shutil.which("godot") or shutil.which("godot4")
    if not executable and sys.platform == "darwin":
        executable = "/Applications/Godot.app/Contents/MacOS/Godot"
    executable = shutil.which(executable) if executable else None
    if not executable:
        parser.error("Godot not found; pass --godot PATH or set GODOT_EXE")

    gallery = args.gallery or bool(args.photo)
    photos = [photo.resolve() for photo in args.photo]
    if gallery and not photos:
        local = [ROOT / ".holoframe-photos" / f"photo-{n}.jpg" for n in (1, 2, 3)]
        photos = local if all(p.is_file() for p in local) else [ROOT / "photos/photo-3.jpg"]
    for photo in photos:
        if not photo.is_file():
            parser.error(f"Photo not found: {photo}")

    photo_args = []
    for photo in photos:
        stem = re.sub(r"[^a-zA-Z0-9]", "_", photo.stem)
        cache = ROOT / ".holoframe-photos"
        outputs = [cache / f"{stem}-{name}.{extension}" for name, extension in
                   (("depth", "png"), ("background", "png"), ("foreground", "png"), ("color", "jpg"))]
        depth, background, foreground, color = outputs
        if (not all(p.is_file() for p in outputs)
                or max(photo.stat().st_mtime, (ROOT / "prepare_photo.py").stat().st_mtime)
                > depth.stat().st_mtime):
            subprocess.run([sys.executable, str(ROOT / "prepare_photo.py"),
                            str(photo), *map(str, outputs)], cwd=ROOT, check=True)
        photo_args.extend(["--photo", str(color), "--depth", str(depth),
                           "--background", str(background), "--foreground", str(foreground)])

    # A fresh clone has no imported Godot assets yet.
    subprocess.run([executable, "--headless", "--editor", "--path", str(ROOT / "godot"),
                    "--import"], cwd=ROOT, check=True)
    tracker_args = []
    if args.camera_index is not None:
        tracker_args.extend(["--camera-index", str(args.camera_index)])
    if args.reset_camera:
        tracker_args.append("--reset-camera")
    tracker = subprocess.Popen([sys.executable, str(ROOT / "godot_tracker.py"), *tracker_args],
                               cwd=ROOT)
    try:
        command = [executable, "--fullscreen", "--path", str(ROOT / "godot"),
                   "--scene", "res://gallery.tscn" if gallery else "res://main.tscn"]
        if photo_args:
            command.extend(["--", *photo_args])
        return subprocess.call(command, cwd=ROOT)
    finally:
        if tracker.poll() is None:
            if os.name == "nt":
                # Camera capture runs in a child process; release the entire tree.
                subprocess.run(["taskkill", "/PID", str(tracker.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                tracker.terminate()
            tracker.wait()


if __name__ == "__main__":
    sys.exit(main())
