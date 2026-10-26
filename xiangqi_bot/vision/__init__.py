"""视觉模块。"""

from .calibrate import Calibration, interactive_calibrate, load_or_calibrate
from .capture import Region, ScreenCapture
from .detect import TemplateDetector, annotate_board

__all__ = [
    "Calibration",
    "interactive_calibrate",
    "load_or_calibrate",
    "Region",
    "ScreenCapture",
    "TemplateDetector",
    "annotate_board",
]
