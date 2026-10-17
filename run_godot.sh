#!/bin/zsh
# Run the camera sidecar with the selected Godot scene and release it on exit.
set -e
cd "$(dirname "$0")"
tracker_args=()
godot_args=()
photos=()
scene=cornell
preset_gallery=false
while (( $# > 0 )); do
    case "$1" in
        --cornell)
            scene=cornell
            shift
            ;;
        --gallery)
            scene=gallery
            preset_gallery=true
            shift
            ;;
        --photo)
            if (( $# < 2 || ${#photos} >= 3 )); then
                print -u2 'Expected --photo PATH (up to three photos)'
                exit 2
            fi
            scene=gallery
            photos+=("${2:A}")
            shift 2
            ;;
        --reset-camera)
            tracker_args+=(--reset-camera)
            shift
            ;;
        --camera-index)
            if (( $# < 2 )); then
                print -u2 'Expected --camera-index N'
                exit 2
            fi
            tracker_args+=(--camera-index "$2")
            shift 2
            ;;
        <->)
            tracker_args+=(--camera-index "$1")
            shift
            ;;
        *)
            print -u2 'Usage: ./run_godot.sh [--cornell | --gallery | --photo PATH ...] [--camera-index N] [--reset-camera]'
            exit 2
            ;;
    esac
done
if [[ "$preset_gallery" == true && ${#photos} == 0 ]]; then
    if [[ -f .holoframe-photos/photo-1.jpg && -f .holoframe-photos/photo-2.jpg && -f .holoframe-photos/photo-3.jpg ]]; then
        for n in 1 2 3; do
            photos+=("${PWD}/.holoframe-photos/photo-${n}.jpg")
        done
    else
        photos+=("${PWD}/photos/photo-3.jpg")
    fi
fi
if [[ "$scene" == gallery ]]; then
    if (( ${#photos} == 0 )); then
        print -u2 'Gallery needs --photo PATH or the local --gallery photo set'
        exit 2
    fi
    for photo in "${photos[@]}"; do
        if [[ ! -f "$photo" ]]; then
            print -u2 "Photo not found: $photo"
            exit 2
        fi
        mkdir -p .holoframe-photos
        stem="${${photo:t:r}//[^[:alnum:]]/_}"
        depth="${PWD}/.holoframe-photos/${stem}-depth.png"
        background="${PWD}/.holoframe-photos/${stem}-background.png"
        foreground="${PWD}/.holoframe-photos/${stem}-foreground.png"
        color="${PWD}/.holoframe-photos/${stem}-color.jpg"
        if [[ ! -f "$depth" || ! -f "$background" || ! -f "$foreground" || ! -f "$color" || "$photo" -nt "$depth" || prepare_photo.py -nt "$depth" ]]; then
            .venv/bin/python prepare_photo.py "$photo" "$depth" "$background" "$foreground" "$color"
        fi
        godot_args+=(--photo "$color" --depth "$depth" --background "$background" --foreground "$foreground")
    done
fi
.venv/bin/python godot_tracker.py "${tracker_args[@]}" &
tracker_pid=$!
trap 'kill "$tracker_pid" 2>/dev/null || true' EXIT INT TERM
if [[ "$scene" == gallery ]]; then
    /Applications/Godot.app/Contents/MacOS/Godot --fullscreen --path godot --scene res://gallery.tscn -- "${godot_args[@]}"
else
    /Applications/Godot.app/Contents/MacOS/Godot --fullscreen --path godot --scene res://main.tscn
fi
