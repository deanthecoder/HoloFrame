from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class AppConfig:
    translation_scale: float = 0.125
    recenter_lerp_rate: float = 0.75
    model_max_size_mm: float = 250.0
    model_path: str = "models/teapot"
    default_camera_pos_mm: Tuple[float, float, float] = (0.0, 0.0, 500.0)
    smoothing_min_cutoff: float = 0.1
    smoothing_beta: float = 0.01
    smoothing_dcutoff: float = 1.0

    @property
    def cube_distance_mm(self) -> float:
        return self.model_max_size_mm / 2.0

    @property
    def cube_size_mm(self) -> float:
        return self.model_max_size_mm
