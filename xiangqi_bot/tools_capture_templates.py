"""交互采集 14 种棋子模板。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .board import PIECE_NAMES, Square, fen_to_label
from .control.mouse import enable_dpi_awareness
from .vision.calibrate import Calibration, load_or_calibrate
from .vision.capture import ScreenCapture
from .vision.window import bring_to_front, find_xiangqi_window

# Windows 文件名不区分大小写，必须用 red_R / black_r
ORDER = list("RNBAKCP") + list("rnbakcp")


def run_capture_templates(cfg: dict, force: bool = False) -> None:
    enable_dpi_awareness()
    vis = cfg["vision"]
    out_dir = Path(vis["templates_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    calib = load_or_calibrate(vis["calib_file"], cfg["screen"].get("monitor", 1))
    board_img = _grab_board(cfg, calib)

    # 与 calib_preview 对齐：先落盘一份供核对
    preview = board_img.copy()
    _overlay_grid(preview, calib)
    preview_path = Path(vis["calib_file"]).parent / "templates_capture_preview.png"
    cv2.imencode(".png", preview)[1].tofile(str(preview_path))
    print(f"采集用截图已保存: {preview_path}（应与 calib_preview 棋盘一致）")

    print("模板采集说明：")
    print("  - 窗口显示当前棋盘截图（与校准区域相同）")
    print("  - 用鼠标左键点击目标棋子中心")
    print("  - 按 Enter 保存该棋子模板，S 跳过，R 重截图，Esc 退出")

    win = "采集模板 - 点棋子中心后 Enter"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    max_w, max_h = 1000, 1100
    scale = min(1.0, max_w / board_img.shape[1], max_h / board_img.shape[0])
    disp_size = (int(board_img.shape[1] * scale), int(board_img.shape[0] * scale))
    state = {"click": None}  # 图像坐标（未缩放）

    def on_mouse(event, x, y, flags, param):  # noqa: ARG001
        if event == cv2.EVENT_LBUTTONDOWN:
            state["click"] = (int(x / scale), int(y / scale))

    cv2.setMouseCallback(win, on_mouse)

    for piece in ORDER:
        label = fen_to_label(piece)
        target = out_dir / f"{label}.png"
        if target.exists() and not force:
            print(f"已存在 {label} ({PIECE_NAMES[piece]})，跳过")
            continue

        state["click"] = None
        print(f"\n请点击: {label} {PIECE_NAMES[piece]}")
        while True:
            view = board_img.copy()
            _overlay_grid(view, calib)
            if state["click"]:
                cv2.circle(view, state["click"], 14, (0, 255, 0), 2)
            cv2.putText(
                view,
                f"{label} {PIECE_NAMES[piece]}  Enter=save S=skip R=reshoot",
                (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 255),
                2,
            )
            cv2.imshow(win, cv2.resize(view, disp_size))
            key = cv2.waitKey(30) & 0xFF
            if key in (13, 10):
                if not state["click"]:
                    print("请先点击棋子中心")
                    continue
                roi = _crop_around(board_img, state["click"], calib)
                ok, buf = cv2.imencode(".png", roi)
                if not ok:
                    print("保存失败")
                    continue
                buf.tofile(str(target))
                print(f"已保存 {target}")
                break
            if key in (ord("s"), ord("S")):
                print("跳过")
                break
            if key in (ord("r"), ord("R")):
                board_img = _grab_board(cfg, calib)
                state["click"] = None
                print("已重新截图")
            if key == 27:
                cv2.destroyWindow(win)
                print("退出采集")
                return

    cv2.destroyWindow(win)
    print("模板采集完成:", out_dir)


def _grab_board(cfg: dict, calib: Calibration) -> np.ndarray:
    game = find_xiangqi_window()
    if game is not None:
        try:
            bring_to_front(game.hwnd)
        except Exception:
            pass
        import time

        time.sleep(0.25)
    with ScreenCapture(cfg["screen"].get("monitor", 1)) as cap:
        return cap.grab_region(calib.region)


def _overlay_grid(img: np.ndarray, calib: Calibration) -> None:
    h, w = img.shape[:2]
    for file in range(9):
        for rank in range(10):
            x, y = calib.square_center_in_image(Square(file, rank), w, h)
            cv2.circle(img, (int(x), int(y)), 3, (80, 80, 255), -1)


def _crop_around(img: np.ndarray, click: tuple[int, int], calib: Calibration, scale: float = 0.85) -> np.ndarray:
    h, w = img.shape[:2]
    cell_w = w / calib.col_span
    cell_h = h / calib.row_span
    rw = int(cell_w * scale)
    rh = int(cell_h * scale)
    cx, cy = click
    x1 = max(0, cx - rw // 2)
    y1 = max(0, cy - rh // 2)
    x2 = min(w, cx + rw // 2)
    y2 = min(h, cy + rh // 2)
    return img[y1:y2, x1:x2].copy()
