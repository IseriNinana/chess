"""基于小 CNN / ONNX 的棋子分类检测器。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ..board import ALL_PIECES, Board, Square, iter_squares, validate_piece_counts
from .calibrate import Calibration
from .cls_common import CLASS_CHARS, IMG_SIZE, index_to_char, preprocess_roi
from .detect import CellGuess, TemplateDetector

RED_PIECES = set("RNBAKCP")
BLACK_PIECES = set("rnbakcp")


class CnnDetector:
    """接口与 TemplateDetector 对齐，便于直接替换。"""

    def __init__(
        self,
        model_path: str | Path,
        conf_threshold: float = 0.45,
        empty_threshold: float = 0.35,
        use_ink_gate: bool = True,
    ):
        self.model_path = Path(model_path)
        self.conf_threshold = conf_threshold
        self.empty_threshold = empty_threshold
        self.use_ink_gate = use_ink_gate
        self.match_threshold = conf_threshold
        self._session = None
        self._torch_model = None
        self._backend = ""
        self._load()

    def _load(self) -> None:
        if not self.model_path.exists():
            print(f"警告: CNN 模型不存在: {self.model_path}")
            return
        suffix = self.model_path.suffix.lower()
        if suffix == ".onnx":
            try:
                import onnxruntime as ort

                self._session = ort.InferenceSession(
                    str(self.model_path),
                    providers=["CPUExecutionProvider"],
                )
                self._backend = "onnx"
                return
            except Exception as exc:
                print(f"ONNX 加载失败，尝试 PyTorch: {exc}")
        # .pt / .pth 或 onnx 失败
        try:
            import torch

            from .cnn_model import build_model

            model = build_model()
            state = torch.load(str(self.model_path), map_location="cpu", weights_only=False)
            if isinstance(state, dict) and "model" in state:
                model.load_state_dict(state["model"])
            elif isinstance(state, dict) and "state_dict" in state:
                model.load_state_dict(state["state_dict"])
            else:
                model.load_state_dict(state)
            model.eval()
            self._torch_model = model
            self._backend = "torch"
        except Exception as exc:
            print(f"警告: 无法加载 CNN 模型: {exc}")

    @property
    def ready(self) -> bool:
        return self._session is not None or self._torch_model is not None

    def _predict_logits(self, roi: np.ndarray) -> np.ndarray:
        x = preprocess_roi(roi, IMG_SIZE)
        if self._session is not None:
            name = self._session.get_inputs()[0].name
            out = self._session.run(None, {name: x})[0]
            return np.asarray(out[0], dtype=np.float32)
        assert self._torch_model is not None
        import torch

        with torch.no_grad():
            t = torch.from_numpy(x)
            logits = self._torch_model(t).cpu().numpy()[0]
        return np.asarray(logits, dtype=np.float32)

    @staticmethod
    def _softmax(logits: np.ndarray) -> np.ndarray:
        z = logits - float(np.max(logits))
        e = np.exp(z)
        return e / max(float(e.sum()), 1e-9)

    def classify_roi(self, roi: np.ndarray, force: bool = False) -> tuple[str, float]:
        if not self.ready or roi.size == 0 or min(roi.shape[:2]) < 8:
            return ".", 0.0

        if self.use_ink_gate and not force:
            side = TemplateDetector._ink_side(roi)
            if side is None:
                return ".", 0.0
        else:
            side = None

        logits = self._predict_logits(roi)
        probs = self._softmax(logits)

        # 颜色先验：压低对方颜色概率
        if side == "red":
            for i, ch in enumerate(CLASS_CHARS):
                if ch in BLACK_PIECES:
                    probs[i] *= 0.15
        elif side == "black":
            for i, ch in enumerate(CLASS_CHARS):
                if ch in RED_PIECES:
                    probs[i] *= 0.15
        probs = probs / max(float(probs.sum()), 1e-9)

        idx = int(np.argmax(probs))
        piece = index_to_char(idx)
        score = float(probs[idx])

        cut = self.empty_threshold * (0.75 if force else 1.0)
        if piece == "." or score < cut:
            # 若最高是空但置信低且强制，取第二高非空
            if force and piece == ".":
                order = np.argsort(probs)[::-1]
                for j in order:
                    ch = index_to_char(int(j))
                    if ch != "." and float(probs[j]) >= cut * 0.8:
                        return ch, float(probs[j])
            return ".", score
        if score < self.conf_threshold and not force:
            # 低置信当空，避免乱填
            if piece != "." and score >= cut:
                return piece, score
            return ".", score
        return piece, score

    def detect_board(
        self,
        image: np.ndarray,
        calib: Calibration,
        side_to_move: str = "w",
    ) -> tuple[Board, list[CellGuess]]:
        guesses: list[CellGuess] = []
        board = Board.empty()
        board.side_to_move = side_to_move
        for sq in iter_squares():
            roi = calib.cell_roi(image, sq, scale=0.85)
            piece, score = self.classify_roi(roi)
            guesses.append(CellGuess(sq, piece, score))
            board.set_piece(sq, piece)
        board = self._maybe_fix_counts(board, guesses)
        return board, guesses

    def mean_confidence(self, guesses: list[CellGuess]) -> float:
        occupied = [g.score for g in guesses if g.piece != "."]
        if not occupied:
            return 0.0
        return float(sum(occupied) / len(occupied))

    def low_confidence_cells(self, guesses: list[CellGuess]) -> list[CellGuess]:
        return [g for g in guesses if g.piece != "." and g.score < self.conf_threshold]

    def _maybe_fix_counts(self, board: Board, guesses: list[CellGuess]) -> Board:
        issues = validate_piece_counts(board)
        if not issues:
            return board
        fixed = board.copy()
        counts: dict[str, list[CellGuess]] = {p: [] for p in ALL_PIECES}
        for g in guesses:
            if g.piece in counts:
                counts[g.piece].append(g)
        from ..board import EXPECTED_COUNTS

        for piece, expected in EXPECTED_COUNTS.items():
            cells = sorted(counts[piece], key=lambda g: g.score, reverse=True)
            for extra in cells[expected:]:
                fixed.set_piece(extra.square, ".")
        return fixed
