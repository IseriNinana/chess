"""屏幕截图。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import mss
import numpy as np


@dataclass
class Region:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def as_mss(self) -> dict[str, int]:
        return {
            "left": int(self.left),
            "top": int(self.top),
            "width": int(self.width),
            "height": int(self.height),
        }

    def clamp_to(self, monitor: dict[str, int]) -> "Region":
        left = max(monitor["left"], self.left)
        top = max(monitor["top"], self.top)
        right = min(monitor["left"] + monitor["width"], self.right)
        bottom = min(monitor["top"] + monitor["height"], self.bottom)
        return Region(left, top, max(1, right - left), max(1, bottom - top))

    def to_dict(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Region":
        return cls(
            int(data["left"]),
            int(data["top"]),
            int(data["width"]),
            int(data["height"]),
        )


class ScreenCapture:
    def __init__(self, monitor_index: int = 1):
        self.monitor_index = monitor_index
        self._sct = mss.mss()

    def close(self) -> None:
        self._sct.close()

    def __enter__(self) -> "ScreenCapture":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def monitors(self) -> list[dict[str, int]]:
        return list(self._sct.monitors)

    def grab_monitor(self) -> np.ndarray:
        mon = self._sct.monitors[self.monitor_index]
        shot = self._sct.grab(mon)
        return self._to_bgr(shot)

    def grab_region(self, region: Region) -> np.ndarray:
        shot = self._sct.grab(region.as_mss())
        return self._to_bgr(shot)

    def grab_fullscreen(self) -> np.ndarray:
        shot = self._sct.grab(self._sct.monitors[0])
        return self._to_bgr(shot)

    @staticmethod
    def _to_bgr(shot: Any) -> np.ndarray:
        img = np.asarray(shot, dtype=np.uint8)
        return img[:, :, :3].copy()
