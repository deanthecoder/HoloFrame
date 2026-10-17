from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    # Display dimensions and webcam height are loaded from godot/display_profile.json.
    screen_width_mm: float = 302.4
    webcam_above_screen_mm: float = 3.3
    webcam_horizontal_offset_mm: float = 0.0
    translation_scale: float = 0.125
    smoothing_min_cutoff: float = 0.1
    smoothing_beta: float = 0.01
    smoothing_dcutoff: float = 1.0
