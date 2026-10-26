"""棋盘区域校准与网格映射。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..board import Square
from .capture import Region, ScreenCapture


@dataclass
class Calibration:
    region: Region
    # 可选：四个角精细校正（左下、右下、右上、左上），像素相对 region
    corners: list[tuple[float, float]] | None = None
    # 上下/左右各留几格边距（0.5 = 半格），避免边缘棋子被裁切
    pad_y_cells: float = 0.5
    pad_x_cells: float = 0.5
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "region": self.region.to_dict(),
            "corners": self.corners,
            "pad_y_cells": self.pad_y_cells,
            "pad_x_cells": self.pad_x_cells,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Calibration":
        corners = data.get("corners")
        if corners is not None:
            corners = [(float(a), float(b)) for a, b in corners]
        return cls(
            Region.from_dict(data["region"]),
            corners,
            float(data.get("pad_y_cells", 0.5)),
            float(data.get("pad_x_cells", 0.0)),
            data.get("note", ""),
        )

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Calibration":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    @property
    def row_span(self) -> float:
        """图像高度对应的格数：9 格间距 + 上下 padding。"""
        return 9.0 + 2.0 * self.pad_y_cells

    @property
    def col_span(self) -> float:
        """图像宽度对应的格数：8 格间距 + 左右 padding。"""
        return 8.0 + 2.0 * self.pad_x_cells

    def square_center_in_image(self, sq: Square, image_w: int, image_h: int) -> tuple[float, float]:
        """返回棋盘截图像素坐标（相对 region 图）。"""
        if self.corners and len(self.corners) == 4:
            return self._bilinear(sq, image_w, image_h)
        cell_w = image_w / self.col_span
        cell_h = image_h / self.row_span
        x = (self.pad_x_cells + sq.file) * cell_w
        y = (self.pad_y_cells + (9 - sq.rank)) * cell_h
        return x, y

    def _bilinear(self, sq: Square, image_w: int, image_h: int) -> tuple[float, float]:
        assert self.corners and len(self.corners) == 4
        _ = (image_w, image_h)
        bl, br, tr, tl = self.corners
        uu = sq.file / 8.0
        vv = (9 - sq.rank) / 9.0
        top_x = tl[0] * (1 - uu) + tr[0] * uu
        top_y = tl[1] * (1 - uu) + tr[1] * uu
        bot_x = bl[0] * (1 - uu) + br[0] * uu
        bot_y = bl[1] * (1 - uu) + br[1] * uu
        x = top_x * (1 - vv) + bot_x * vv
        y = top_y * (1 - vv) + bot_y * vv
        return x, y

    def cell_roi(
        self,
        image: np.ndarray,
        sq: Square,
        scale: float = 0.72,
    ) -> np.ndarray:
        """裁剪交叉点附近的棋子 ROI。"""
        h, w = image.shape[:2]
        cx, cy = self.square_center_in_image(sq, w, h)
        cell_w = w / self.col_span
        cell_h = h / self.row_span
        rw = cell_w * scale
        rh = cell_h * scale
        x1 = int(max(0, cx - rw / 2))
        y1 = int(max(0, cy - rh / 2))
        x2 = int(min(w, cx + rw / 2))
        y2 = int(min(h, cy + rh / 2))
        return image[y1:y2, x1:x2].copy()


def interactive_calibrate(monitor_index: int = 1, save_path: str | Path = "data/calib.json") -> Calibration:
    """拖拽框选棋盘外接矩形。优先在象棋窗口内框选。Enter确认，R重选，Esc取消。"""
    from ..control.mouse import enable_dpi_awareness
    from .window import bring_to_front, find_xiangqi_window

    enable_dpi_awareness()

    origin_left = 0
    origin_top = 0
    game = find_xiangqi_window()
    with ScreenCapture(monitor_index) as cap:
        if game is not None:
            bring_to_front(game.hwnd)
            import time

            time.sleep(0.35)
            # 窗口可能 top 为负（贴边），截图时 clamp
            origin_left = game.left
            origin_top = max(0, game.top)
            grab_h = game.height - (origin_top - game.top)
            frame = cap.grab_region(Region(origin_left, origin_top, game.width, max(1, grab_h)))
            print(f"基于游戏窗口截图: {game.title} @({game.left},{game.top}) {game.width}x{game.height}")
        else:
            mon = cap.monitors()[monitor_index]
            origin_left, origin_top = mon["left"], mon["top"]
            frame = cap.grab_monitor()
            print("未找到象棋窗口，使用整屏截图。请尽量只框棋盘。")

    clone = frame.copy()
    selecting = {"x0": 0, "y0": 0, "x1": 0, "y1": 0, "down": False, "done": False}

    win = "校准棋盘 - 只框选棋盘交叉点外框，Enter确认"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    max_w, max_h = 1200, 900
    scale = min(1.0, max_w / frame.shape[1], max_h / frame.shape[0])
    disp_size = (int(frame.shape[1] * scale), int(frame.shape[0] * scale))

    def on_mouse(event, x, y, flags, param):  # noqa: ARG001
        ox, oy = int(x / scale), int(y / scale)
        if event == cv2.EVENT_LBUTTONDOWN:
            selecting["down"] = True
            selecting["x0"] = selecting["x1"] = ox
            selecting["y0"] = selecting["y1"] = oy
        elif event == cv2.EVENT_MOUSEMOVE and selecting["down"]:
            selecting["x1"] = ox
            selecting["y1"] = oy
        elif event == cv2.EVENT_LBUTTONUP:
            selecting["down"] = False
            selecting["x1"] = ox
            selecting["y1"] = oy

    cv2.setMouseCallback(win, on_mouse)

    while True:
        view = clone.copy()
        x0, y0 = selecting["x0"], selecting["y0"]
        x1, y1 = selecting["x1"], selecting["y1"]
        if x0 != x1 and y0 != y1:
            cv2.rectangle(view, (x0, y0), (x1, y1), (0, 255, 0), 2)
            _draw_grid_preview(view, x0, y0, x1, y1)
        disp = cv2.resize(view, disp_size)
        cv2.imshow(win, disp)
        key = cv2.waitKey(20) & 0xFF
        if key in (13, 10):  # Enter
            if abs(x1 - x0) > 20 and abs(y1 - y0) > 20:
                selecting["done"] = True
                break
        elif key in (ord("r"), ord("R")):
            selecting.update(x0=0, y0=0, x1=0, y1=0)
        elif key == 27:
            cv2.destroyWindow(win)
            raise SystemExit("校准取消")

    cv2.destroyWindow(win)
    left = min(x0, x1) + origin_left
    top = min(y0, y1) + origin_top
    width = abs(x1 - x0)
    height = abs(y1 - y0)
    # 用户框的是交叉点外框；上下左右各扩半格，避免边缘棋子被裁切
    pad_y = 0.5
    pad_x = 0.5
    cell_w = width / 8.0
    cell_h = height / 9.0
    left = int(round(left - pad_x * cell_w))
    top = int(round(top - pad_y * cell_h))
    width = int(round(width + 2 * pad_x * cell_w))
    height = int(round(height + 2 * pad_y * cell_h))
    if left < 0:
        width += left
        left = 0
    if top < 0:
        height += top
        top = 0
    calib = Calibration(
        Region(left, top, max(1, width), max(1, height)),
        pad_y_cells=pad_y,
        pad_x_cells=pad_x,
        note=("window-drag" if game else "drag-rect") + "+pad_xy0.5",
    )
    calib.save(save_path)
    # 记录窗口锚点，窗口移动后可自动平移校准区
    if game is not None:
        import json as _json
        data = _json.loads(Path(save_path).read_text(encoding="utf-8"))
        data["window_anchor"] = {
            "left": game.left,
            "top": game.top,
            "width": game.width,
            "height": game.height,
        }
        Path(save_path).write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已保存校准: {save_path} -> {calib.region} (四周各留半格)")
    return calib


def _draw_grid_preview(img: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> None:
    left, right = sorted([x0, x1])
    top, bottom = sorted([y0, y1])
    w, h = right - left, bottom - top
    cell_w = w / 8.0
    cell_h = h / 9.0
    pad_x = int(round(cell_w * 0.5))
    pad_y = int(round(cell_h * 0.5))
    cv2.rectangle(img, (left - pad_x, top - pad_y), (right + pad_x, bottom + pad_y), (255, 180, 0), 1)
    for i in range(9):
        x = int(left + i * w / 8.0)
        cv2.line(img, (x, top), (x, bottom), (0, 200, 255), 1)
    for j in range(10):
        y = int(top + j * h / 9.0)
        cv2.line(img, (left, y), (right, y), (0, 200, 255), 1)


def mss_monitor_offset(monitor_index: int) -> dict[str, int]:
    with ScreenCapture(monitor_index) as cap:
        return dict(cap.monitors()[monitor_index])


def load_or_calibrate(calib_file: str | Path, monitor_index: int = 1) -> Calibration:
    path = Path(calib_file)
    if path.exists():
        return Calibration.load(path)
    print("未找到校准文件，开始交互校准…")
    return interactive_calibrate(monitor_index, path)
