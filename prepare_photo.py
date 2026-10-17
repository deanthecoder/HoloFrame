"""Estimate a single photo's relative depth for HoloFrame's 3D photo view."""

import argparse
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


MODEL = "depth-anything/Depth-Anything-V2-Small-hf"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("photo", type=Path)
    parser.add_argument("depth", type=Path)
    parser.add_argument("background", type=Path)
    parser.add_argument("foreground", type=Path)
    parser.add_argument("color", type=Path)
    args = parser.parse_args()

    # Keep the sizeable inference dependencies optional for the normal room view.
    try:
        import torch
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    except ImportError as error:
        parser.error(f"install the photo dependencies first: {error}")

    photo = Image.open(args.photo).convert("RGB")
    photo.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    args.color.parent.mkdir(parents=True, exist_ok=True)
    photo.save(args.color, quality=93)
    processor = AutoImageProcessor.from_pretrained(MODEL, use_fast=False)
    model = AutoModelForDepthEstimation.from_pretrained(MODEL).eval()
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model.to(device)
    inputs = processor(images=photo, return_tensors="pt").to(device)
    with torch.inference_mode():
        prediction = model(**inputs).predicted_depth
        prediction = torch.nn.functional.interpolate(
            prediction.unsqueeze(1),
            size=(256, 192),
            mode="bicubic",
            align_corners=False,
        ).squeeze().cpu().numpy()

    lo, hi = np.percentile(prediction, (2, 98))
    depth = np.clip((prediction - lo) / max(hi - lo, 1e-6), 0, 1)
    depth = cv2.GaussianBlur(depth.astype(np.float32), (3, 3), 0)

    # The plate only shows through newly uncovered slivers. Its unseen interior
    # is a local approximation, not a reconstruction of the true background.
    rgb = np.asarray(photo)
    full_depth = cv2.resize(depth, (photo.width, photo.height))
    import mediapipe as mp

    with mp.solutions.selfie_segmentation.SelfieSegmentation(model_selection=1) as segmenter:
        person = segmenter.process(rgb).segmentation_mask
    if person is not None and np.mean(person > 0.5) > 0.01:
        alpha = np.clip((person - 0.35) / 0.30, 0, 1)
        # Monocular depth tends to fade into the background at a silhouette.
        # Extend depth from the safe interior to the cutout edge so side views
        # do not stretch those edge polygons backwards.
        person_small = cv2.resize(alpha, (depth.shape[1], depth.shape[0])) > 0.5
        core = cv2.erode(person_small.astype(np.uint8), np.ones((7, 7), np.uint8))
        if np.any(core):
            _, labels = cv2.distanceTransformWithLabels(
                1 - core, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL
            )
            nearest_depth = np.zeros(labels.max() + 1, np.float32)
            nearest_depth[labels[core > 0]] = depth[core > 0]
            edge = person_small & (core == 0)
            depth[edge] = np.maximum(depth[edge], nearest_depth[labels[edge]])
    else:
        # Keep generic photos usable when there is no person to segment.
        alpha = np.clip((full_depth - 0.14) / 0.10, 0, 1)

    args.depth.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.depth), np.round(depth * 255).astype(np.uint8)):
        raise OSError(f"Could not write depth map: {args.depth}")
    alpha = cv2.GaussianBlur(alpha.astype(np.float32), (5, 5), 0)
    foreground = np.dstack((rgb, np.round(alpha * 255).astype(np.uint8)))
    args.foreground.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(foreground).save(args.foreground)
    mask = np.uint8(alpha > 0.02) * 255
    mask = cv2.dilate(mask, np.ones((15, 15), np.uint8))
    background = cv2.inpaint(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), mask, 15, cv2.INPAINT_TELEA)
    args.background.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.background), background):
        raise OSError(f"Could not write background plate: {args.background}")
    print(f"Prepared {args.photo.name} using {MODEL} on {device}")


if __name__ == "__main__":
    main()
