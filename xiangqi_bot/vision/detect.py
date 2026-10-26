"""基于 OpenCV 模板匹配的棋子识别。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ..board import ALL_PIECES, Board, Square, iter_squares, validate_piece_counts
from .calibrate import Calibration

RED_PIECES = set("RNBAKCP")
BLACK_PIECES = set("rnbakcp")


@dataclass
class CellGuess:
    square: Square
    piece: str
    score: float


class TemplateDetector:
    """
    模板命名约定（放在 templates_dir）：
      red_R.png / black_r.png ...（Windows 不区分大小写，禁止只用 R/r）
    也支持中文别名文件，见 ALIASES。
    """

    ALIASES = {
        "红车": "R",
        "红马": "N",
        "红相": "B",
        "红仕": "A",
        "红帅": "K",
        "红炮": "C",
        "红兵": "P",
        "黑车": "r",
        "黑马": "n",
        "黑象": "b",
        "黑士": "a",
        "黑将": "k",
        "黑炮": "c",
        "黑卒": "p",
        "red_R": "R",
        "red_N": "N",
        "red_B": "B",
        "red_A": "A",
        "red_K": "K",
        "red_C": "C",
        "red_P": "P",
        "black_r": "r",
        "black_n": "n",
        "black_b": "b",
        "black_a": "a",
        "black_k": "k",
        "black_c": "c",
        "black_p": "p",
    }

    def __init__(
        self,
        templates_dir: str | Path,
        match_threshold: float = 0.42,
        empty_threshold: float = 0.32,
    ):
        self.templates_dir = Path(templates_dir)
        self.match_threshold = match_threshold
        self.empty_threshold = empty_threshold
        self.templates: dict[str, np.ndarray] = {}
        self.reload()

    def reload(self) -> None:
        self.templates.clear()
        if not self.templates_dir.exists():
            return
        for path in self.templates_dir.glob("*.*"):
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp"}:
                continue
            key = path.stem
            piece = self.ALIASES.get(key)
            if piece is None and key in ALL_PIECES:
                piece = key
                print(f"警告: 模板 {path.name} 使用单字母名，Windows 下红黑可能互相覆盖")
            if piece not in ALL_PIECES:
                continue
            img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            self.templates[piece] = img
        if not self.templates:
            print(f"警告: 未在 {self.templates_dir} 加载到棋子模板")

    @property
    def ready(self) -> bool:
        return len(self.templates) >= 7

    def classify_roi(self, roi: np.ndarray, force: bool = False) -> tuple[str, float]:
        if roi.size == 0 or min(roi.shape[:2]) < 8:
            return ".", 0.0

        side = self._ink_side(roi)
        if side is None and not force:
            # 无明显红/黑字迹 → 空位（避免木纹误匹配）
            return ".", 0.0

        if side == "red":
            want = RED_PIECES
        elif side == "black":
            want = BLACK_PIECES
        else:
            want = ALL_PIECES
        candidates = {k: v for k, v in self.templates.items() if k in want}
        if not candidates:
            return ".", 0.0

        best_piece = "."
        best_score = -1.0
        for piece, tmpl in candidates.items():
            score = self._match_score(roi, tmpl)
            if score > best_score:
                best_score = score
                best_piece = piece

        empty_cut = self.empty_threshold * (0.75 if force else 1.0)
        if best_score < empty_cut:
            return ".", best_score
        return best_piece, best_score

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
        return [g for g in guesses if g.piece != "." and g.score < self.match_threshold]

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

    @staticmethod
    def _ink_side(roi: np.ndarray) -> str | None:
        """根据字符颜色判断红/黑；空位返回 None。"""
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        h, w = roi.shape[:2]
        cy, cx = h // 2, w // 2
        rad = int(min(h, w) * 0.38)
        mask = np.zeros((h, w), np.uint8)
        cv2.circle(mask, (cx, cy), rad, 255, -1)

        red1 = cv2.inRange(hsv, (0, 50, 50), (12, 255, 255))
        red2 = cv2.inRange(hsv, (165, 50, 50), (180, 255, 255))
        red = cv2.bitwise_and(cv2.bitwise_or(red1, red2), mask)

        # 黑字：暗色且非明显红色（阈值放宽，避免漏认黑马）
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        dark = cv2.inRange(gray, 0, 120)
        dark = cv2.bitwise_and(dark, mask)
        dark = cv2.bitwise_and(dark, cv2.bitwise_not(red))

        red_n = int(cv2.countNonZero(red))
        dark_n = int(cv2.countNonZero(dark))
        area = max(1, int(cv2.countNonZero(mask)))
        # 黑马/黑象字迹常偏淡，阈值略放宽
        if red_n < area * 0.008 and dark_n < area * 0.01:
            return None
        if red_n >= dark_n and red_n >= area * 0.006:
            return "red"
        if dark_n >= area * 0.01:
            return "black"
        return None

    @staticmethod
    def _match_score(roi: np.ndarray, tmpl: np.ndarray) -> float:
        rh, rw = roi.shape[:2]
        th, tw = tmpl.shape[:2]
        if min(rh, rw, th, tw) < 8:
            return -1.0

        scores: list[float] = []
        for scale in (0.92, 1.0, 1.08):
            nw = max(12, int(rw * scale))
            nh = max(12, int(rh * scale))
            probe = cv2.resize(tmpl, (nw, nh), interpolation=cv2.INTER_AREA)
            base = cv2.resize(roi, (nw, nh), interpolation=cv2.INTER_AREA)

            # 灰度（轻度）
            ag = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)
            bg = cv2.cvtColor(probe, cv2.COLOR_BGR2GRAY)
            res = cv2.matchTemplate(ag, bg, cv2.TM_CCOEFF_NORMED)
            scores.append(float(res.max()))

            # 彩色：更区分红黑字
            for c in range(3):
                res_c = cv2.matchTemplate(base[:, :, c], probe[:, :, c], cv2.TM_CCOEFF_NORMED)
                scores.append(float(res_c.max()))

        return max(scores) if scores else -1.0


def annotate_board(image: np.ndarray, calib: Calibration, board: Board, guesses: list[CellGuess] | None = None) -> np.ndarray:
    """调试可视化。"""
    out = image.copy()
    h, w = out.shape[:2]
    score_map = {g.square: g.score for g in guesses} if guesses else {}
    for sq in iter_squares():
        cx, cy = calib.square_center_in_image(sq, w, h)
        piece = board.piece_at(sq)
        color = (0, 0, 255) if piece.isupper() else (255, 80, 80) if piece.islower() else (180, 180, 180)
        cv2.circle(out, (int(cx), int(cy)), 10, color, 1)
        if piece != ".":
            cv2.putText(
                out,
                piece,
                (int(cx) - 6, int(cy) + 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                color,
                1,
                cv2.LINE_AA,
            )
            sc = score_map.get(sq)
            if sc is not None:
                cv2.putText(
                    out,
                    f"{sc:.2f}",
                    (int(cx) - 12, int(cy) + 18),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.35,
                    (0, 255, 255),
                    1,
                    cv2.LINE_AA,
                )
    return out
