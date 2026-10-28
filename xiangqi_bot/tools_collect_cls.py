"""采集 CNN 分类数据集：按校准切格，用 FEN 自动打标。"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .board import Board, START_FEN, Square, iter_squares
from .control.mouse import enable_dpi_awareness
from .vision.calibrate import Calibration, load_or_calibrate
from .vision.capture import ScreenCapture
from .vision.cls_common import CLASS_CHARS, IMG_SIZE, char_to_folder, ensure_class_dirs
from .vision.window import bring_to_front, find_xiangqi_window


def _save_roi(path: Path, roi: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = cv2.resize(roi, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)
    cv2.imencode(".png", out)[1].tofile(str(path))


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def export_board_cells(
    image: np.ndarray,
    calib: Calibration,
    board: Board,
    out_dir: Path,
    prefix: str = "",
    scales: tuple[float, ...] = (0.70, 0.80, 0.90, 1.00),
    offsets: tuple[tuple[int, int], ...] = ((0, 0),),
) -> int:
    """按 FEN 把每格 ROI 写入对应类别目录。返回写出张数。"""
    ensure_class_dirs(out_dir)
    n = 0
    tag = prefix or _stamp()
    for sq in iter_squares():
        piece = board.piece_at(sq)
        folder = out_dir / char_to_folder(piece)
        for i, scale in enumerate(scales):
            for j, (dx, dy) in enumerate(offsets):
                roi = calib.cell_roi(image, sq, scale=scale, dx=dx, dy=dy)
                if roi.size == 0 or min(roi.shape[:2]) < 8:
                    continue
                name = f"{tag}_{sq.uci}_s{i}_j{j}.png"
                _save_roi(folder / name, roi)
                n += 1
    return n


def bootstrap_from_templates(
    templates_dir: Path,
    out_dir: Path,
    copies: int = 36,
    synth_empty: int = 0,
) -> int:
    """用已有模板图生成增强样本，便于冷启动训练。"""
    from .vision.detect import TemplateDetector

    ensure_class_dirs(out_dir)
    det = TemplateDetector(templates_dir)
    n = 0
    rng = np.random.default_rng(42)
    for piece, img in det.templates.items():
        folder = out_dir / char_to_folder(piece)
        for i in range(copies):
            aug = _augment(img, rng)
            _save_roi(folder / f"tmpl_{piece}_{i}.png", aug)
            n += 1
    empty_dir = out_dir / "empty"
    for i in range(max(0, synth_empty)):
        noise = rng.integers(40, 120, (IMG_SIZE, IMG_SIZE, 3), dtype=np.uint8)
        noise[:, :, 0] = (noise[:, :, 0].astype(np.int16) * 0.5 + 30).clip(0, 255).astype(np.uint8)
        noise[:, :, 1] = (noise[:, :, 1].astype(np.int16) * 0.7 + 50).clip(0, 255).astype(np.uint8)
        noise[:, :, 2] = (noise[:, :, 2].astype(np.int16) * 0.9 + 70).clip(0, 255).astype(np.uint8)
        _save_roi(empty_dir / f"synth_empty_{i}.png", noise)
        n += 1
    return n


def _augment(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    out = img.copy()
    h, w = out.shape[:2]
    # 轻微缩放
    scale = float(rng.uniform(0.85, 1.15))
    nh, nw = max(8, int(h * scale)), max(8, int(w * scale))
    out = cv2.resize(out, (nw, nh), interpolation=cv2.INTER_LINEAR)
    # pad/crop 回原尺寸附近
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    y0 = max(0, (h - nh) // 2)
    x0 = max(0, (w - nw) // 2)
    y1, x1 = min(h, y0 + nh), min(w, x0 + nw)
    sy1, sx1 = y1 - y0, x1 - x0
    canvas[y0:y1, x0:x1] = out[:sy1, :sx1]
    out = canvas
    # 亮度
    alpha = float(rng.uniform(0.75, 1.25))
    beta = float(rng.uniform(-25, 25))
    out = cv2.convertScaleAbs(out, alpha=alpha, beta=beta)
    if rng.random() < 0.3:
        out = cv2.GaussianBlur(out, (3, 3), 0)
    return out


def run_collect_cls(
    cfg: dict,
    fen: str | None = None,
    assume_start: bool = False,
    from_image: str | None = None,
    bootstrap_templates: bool = False,
    shots: int = 1,
    delay: float = 0.4,
) -> None:
    enable_dpi_awareness()
    vis = cfg["vision"]
    out_dir = Path(vis.get("cls_dataset") or "data/cls_dataset")
    if not out_dir.is_absolute():
        from .config import project_root

        out_dir = project_root() / out_dir
    ensure_class_dirs(out_dir)

    if bootstrap_templates:
        tdir = Path(vis["templates_dir"])
        n = bootstrap_from_templates(tdir, out_dir)
        print(f"已从模板增强写入 {n} 张 -> {out_dir}")

    if assume_start:
        fen = START_FEN
    if fen:
        board = Board.from_fen(fen)
    else:
        board = None

    calib = load_or_calibrate(vis["calib_file"], cfg["screen"].get("monitor", 1))

    if from_image:
        img = cv2.imdecode(np.fromfile(from_image, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(f"无法读取图片: {from_image}")
        if board is None:
            raise RuntimeError("从图片采集必须提供 --fen 或 --assume-start")
        n = export_board_cells(img, calib, board, out_dir)
        print(f"从图片写入 {n} 张 -> {out_dir}")
        _print_counts(out_dir)
        return

    if board is None and not bootstrap_templates:
        raise RuntimeError("请指定 --assume-start / --fen，或 --bootstrap-templates")

    if board is None:
        _print_counts(out_dir)
        return

    try:
        win = find_xiangqi_window()
        if win:
            bring_to_front(win.hwnd)
            time.sleep(0.3)
    except Exception:
        pass

    print(f"按 FEN 采集 {shots} 次: {board.to_fen()}")
    print("请确保象棋窗口在前、棋盘完整可见。")
    time.sleep(1.0)

    total = 0
    with ScreenCapture(cfg["screen"].get("monitor", 1)) as cap:
        for i in range(shots):
            img = cap.grab_region(calib.region)
            n = export_board_cells(img, calib, board, out_dir, prefix=f"cap{_stamp()}_{i}")
            total += n
            print(f"  shot {i + 1}/{shots}: +{n}")
            if i + 1 < shots:
                time.sleep(delay)

    print(f"共写入 {total} 张 -> {out_dir}")
    _print_counts(out_dir)


def _print_counts(out_dir: Path) -> None:
    print("各类数量:")
    for ch in CLASS_CHARS:
        folder = out_dir / char_to_folder(ch)
        n = len(list(folder.glob("*.png"))) if folder.exists() else 0
        print(f"  {char_to_folder(ch):10s} {n}")
