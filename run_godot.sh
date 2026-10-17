#!/bin/zsh
# Run the camera sidecar with Godot and release the camera when Godot exits.
set -e
cd "$(dirname "$0")"
tracker_args=()
if (( $# > 0 )); then
    tracker_args=(--camera-index "$1")
fi
.venv/bin/python godot_tracker.py "${tracker_args[@]}" &
tracker_pid=$!
trap 'kill "$tracker_pid" 2>/dev/null || true' EXIT INT TERM
/Applications/Godot.app/Contents/MacOS/Godot --fullscreen --path godot
