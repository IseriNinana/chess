"""根据配置创建棋子检测器。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import numpy as np

from ..board import Board
from .calibrate import Calibration
from .detect import CellGuess, TemplateDetector


class PieceDetector(Protocol):
    ready: bool

    def classify_roi(self, roi: np.ndarray, force: bool = False) -> tuple[str, float]: ...

    def detect_board(
        self,
        image: np.ndarray,
        calib: Calibration,
        side_to_move: str = "w",
    ) -> tuple[Board, list[CellGuess]]: ...

    def _maybe_fix_counts(self, board: Board, guesses: list[CellGuess]) -> Board: ...


def make_detector(vis: dict[str, Any]) -> PieceDetector:
    backend = str(vis.get("backend", "template")).lower().strip()
    if backend in ("cnn", "onnx", "neural"):
        from .cnn_detect import CnnDetector

        model = vis.get("cnn_model") or "data/models/piece_cls.onnx"
        det = CnnDetector(
            model_path=model,
            conf_threshold=float(vis.get("cnn_conf", 0.45)),
            empty_threshold=float(vis.get("empty_threshold", 0.35)),
            use_ink_gate=bool(vis.get("cnn_ink_gate", True)),
        )
        if det.ready:
            return det
        print(f"CNN 模型不可用 ({model})，回退到 template")
    return TemplateDetector(
        vis["templates_dir"],
        match_threshold=float(vis.get("match_threshold", 0.62)),
        empty_threshold=float(vis.get("empty_threshold", 0.45)),
    )


def detector_status(vis: dict[str, Any]) -> str:
    backend = str(vis.get("backend", "template")).lower()
    if backend in ("cnn", "onnx", "neural"):
        path = Path(vis.get("cnn_model") or "data/models/piece_cls.onnx")
        return f"cnn ({'OK' if path.exists() else '缺少 ' + str(path)})"
    n = 0
    tdir = Path(vis.get("templates_dir", ""))
    if tdir.exists():
        n = len(list(tdir.glob("*.png"))) + len(list(tdir.glob("*.jpg")))
    return f"template ({n} 张)"
