"""棋子 CNN 分类：标签、预处理、共享常量。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ..board import ALL_PIECES, fen_to_label

# 15 类：空 + 14 棋子（顺序固定，训练/推理必须一致）
CLASS_CHARS: list[str] = [".", "R", "N", "B", "A", "K", "C", "P", "r", "n", "b", "a", "k", "c", "p"]
assert len(CLASS_CHARS) == 15
assert set(CLASS_CHARS) == {"."} | ALL_PIECES

IMG_SIZE = 64


def char_to_folder(ch: str) -> str:
    if ch == ".":
        return "empty"
    return fen_to_label(ch)


def folder_to_char(name: str) -> str | None:
    if name in ("empty", ".", "blank"):
        return "."
    if name in CLASS_CHARS:
        return name
    from .detect import TemplateDetector

    return TemplateDetector.ALIASES.get(name)


def char_to_index(ch: str) -> int:
    return CLASS_CHARS.index(ch)


def index_to_char(idx: int) -> str:
    return CLASS_CHARS[idx]


def preprocess_roi(roi: np.ndarray, size: int = IMG_SIZE) -> np.ndarray:
    """BGR ROI -> float32 NCHW RGB [0,1]，单张 shape (1,3,H,W)。"""
    if roi is None or roi.size == 0:
        arr = np.zeros((size, size, 3), dtype=np.uint8)
    else:
        arr = cv2.resize(roi, (size, size), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    chw = np.transpose(rgb, (2, 0, 1))[None, ...]
    return np.ascontiguousarray(chw)


def list_dataset_images(root: Path) -> list[tuple[Path, int]]:
    """扫描 data/cls_dataset/<folder>/*.png -> (path, class_idx)。"""
    items: list[tuple[Path, int]] = []
    if not root.exists():
        return items
    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue
        ch = folder_to_char(folder.name)
        if ch is None or ch not in CLASS_CHARS:
            continue
        idx = char_to_index(ch)
        for path in folder.glob("*.*"):
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}:
                items.append((path, idx))
    return items


def ensure_class_dirs(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for ch in CLASS_CHARS:
        (root / char_to_folder(ch)).mkdir(parents=True, exist_ok=True)
