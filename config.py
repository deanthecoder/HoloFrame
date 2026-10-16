from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class AppConfig:
    # Approximate 15.6-inch laptop; height follows the selected display's aspect ratio.
    screen_width_mm: float = 344.0
    webcam_above_screen_mm: float = 8.0
    webcam_horizontal_offset_mm: float = 0.0
    webcam_index: int = 0
    monitor_index: Optional[int] = None
    translation_scale: float = 0.125
    recenter_lerp_rate: float = 0.75
    model_max_size_mm: float = 150.0
    model_depth_mm: float = -100.0  # Model center; negative is in front of the screen.
    model_path: str = "models/teapot"
    # Screen-relative right, up, and distance towards the viewer.
    default_camera_pos_mm: Tuple[float, float, float] = (0.0, 0.0, 600.0)
    smoothing_min_cutoff: float = 0.1
    smoothing_beta: float = 0.01
    smoothing_dcutoff: float = 1.0

    @property
    def cube_distance_mm(self) -> float:
        return self.model_max_size_mm / 2.0

    @property
    def cube_size_mm(self) -> float:
        return self.model_max_size_mm
