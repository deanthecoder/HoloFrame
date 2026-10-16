"""A stationary screen aperture viewed from a moving eye, in meters."""

from panda3d.core import PerspectiveLens, Point3


def apply_screen_projection(camera, lens: PerspectiveLens, eye_mm, width_mm, height_mm):
    """Map screen-relative (right, up, distance) to Panda's X/right, Y/forward, Z/up."""
    x, up, distance = (float(v) * 0.001 for v in eye_mm)
    distance = max(0.05, distance)
    eye = Point3(x, -distance, up)
    camera.setPos(eye)
    camera.setHpr(0, 0, 0)
    half_w, half_h = width_mm * 0.0005, height_mm * 0.0005
    corners = [Point3(px, 0, pz) - eye for px, pz in
               [(-half_w, half_h), (half_w, half_h),
                (-half_w, -half_h), (half_w, -half_h)]]
    lens.setFrustumFromCorners(*corners, lens.FCOffAxis | lens.FCAspectRatio)
