"""象棋棋盘模型：FEN、坐标、着法。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

RED_PIECES = set("RNBAKCP")
BLACK_PIECES = set("rnbakcp")
ALL_PIECES = RED_PIECES | BLACK_PIECES

PIECE_NAMES = {
    "K": "红帅",
    "A": "红仕",
    "B": "红相",
    "N": "红马",
    "R": "红车",
    "C": "红炮",
    "P": "红兵",
    "k": "黑将",
    "a": "黑士",
    "b": "黑象",
    "n": "黑马",
    "r": "黑车",
    "c": "黑炮",
    "p": "黑卒",
}

PIECE_ZH_SHORT = {
    "K": "帅",
    "A": "仕",
    "B": "相",
    "N": "马",
    "R": "车",
    "C": "炮",
    "P": "兵",
    "k": "将",
    "a": "士",
    "b": "象",
    "n": "马",
    "r": "车",
    "c": "炮",
    "p": "卒",
}

_ZH_NUM = "一二三四五六七八九"

EXPECTED_COUNTS = {
    "K": 1,
    "k": 1,
    "A": 2,
    "a": 2,
    "B": 2,
    "b": 2,
    "N": 2,
    "n": 2,
    "R": 2,
    "r": 2,
    "C": 2,
    "c": 2,
    "P": 5,
    "p": 5,
}

START_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w"

# 模板文件名用的稳定标签（兼容旧命名）
TEMPLATE_LABELS = [
    "red_K",
    "red_A",
    "red_B",
    "red_N",
    "red_R",
    "red_C",
    "red_P",
    "black_k",
    "black_a",
    "black_b",
    "black_n",
    "black_r",
    "black_c",
    "black_p",
]


def label_to_fen(label: str) -> str:
    if label.startswith("red_"):
        return label.split("_", 1)[1].upper()
    if label.startswith("black_"):
        return label.split("_", 1)[1].lower()
    if label in ALL_PIECES:
        return label
    raise ValueError(f"未知模板标签: {label}")


def fen_to_label(ch: str) -> str:
    if ch in RED_PIECES:
        return f"red_{ch}"
    if ch in BLACK_PIECES:
        return f"black_{ch}"
    raise ValueError(f"非法棋子字符: {ch}")


@dataclass(frozen=True)
class Square:
    """棋盘交叉点：file 0..8 (a..i)，rank 0..9。红在 rank0 一侧。"""

    file: int
    rank: int

    def __post_init__(self) -> None:
        if not (0 <= self.file <= 8 and 0 <= self.rank <= 9):
            raise ValueError(f"越界格子: {self}")

    @property
    def uci(self) -> str:
        return f"{chr(ord('a') + self.file)}{self.rank}"

    @classmethod
    def from_uci(cls, text: str) -> "Square":
        text = text.strip().lower()
        if len(text) < 2:
            raise ValueError(f"非法坐标: {text}")
        file = ord(text[0]) - ord("a")
        rank = int(text[1:])
        return cls(file, rank)

    def flip(self) -> "Square":
        return Square(8 - self.file, 9 - self.rank)


@dataclass(frozen=True)
class Move:
    frm: Square
    to: Square

    @property
    def uci(self) -> str:
        return f"{self.frm.uci}{self.to.uci}"

    @classmethod
    def from_uci(cls, text: str) -> "Move":
        text = text.strip().lower()
        if len(text) < 4:
            raise ValueError(f"非法着法: {text}")
        return cls(Square.from_uci(text[0:2]), Square.from_uci(text[2:4]))

    def flip(self) -> "Move":
        return Move(self.frm.flip(), self.to.flip())


class Board:
    """10 行 × 9 列。grid[0] = FEN 第一段 = rank 9（上方）。"""

    def __init__(self, grid: Optional[list[list[str]]] = None, side_to_move: str = "w"):
        if grid is None:
            self.grid = [["."] * 9 for _ in range(10)]
        else:
            if len(grid) != 10 or any(len(r) != 9 for r in grid):
                raise ValueError("棋盘必须是 10x9")
            self.grid = [list(row) for row in grid]
        self.side_to_move = "w" if side_to_move.lower().startswith("w") else "b"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Board):
            return NotImplemented
        return self.grid == other.grid and self.side_to_move == other.side_to_move

    @classmethod
    def empty(cls) -> "Board":
        return cls()

    @classmethod
    def start(cls) -> "Board":
        return cls.from_fen(START_FEN)

    @classmethod
    def starting(cls) -> "Board":
        return cls.start()

    @classmethod
    def from_fen(cls, fen: str) -> "Board":
        parts = fen.strip().split()
        placement = parts[0]
        side = parts[1] if len(parts) > 1 else "w"
        rows = placement.split("/")
        if len(rows) != 10:
            raise ValueError(f"FEN 行数错误: {fen}")
        grid: list[list[str]] = []
        for row in rows:
            cells: list[str] = []
            for ch in row:
                if ch.isdigit():
                    cells.extend(["."] * int(ch))
                else:
                    cells.append(ch)
            if len(cells) != 9:
                raise ValueError(f"FEN 列数错误: {row}")
            grid.append(cells)
        return cls(grid, side)

    def copy(self) -> "Board":
        return Board([list(r) for r in self.grid], self.side_to_move)

    def to_fen(self, include_side: bool = True) -> str:
        parts: list[str] = []
        for row in self.grid:
            empty = 0
            buf: list[str] = []
            for ch in row:
                if ch == ".":
                    empty += 1
                else:
                    if empty:
                        buf.append(str(empty))
                        empty = 0
                    buf.append(ch)
            if empty:
                buf.append(str(empty))
            parts.append("".join(buf))
        placement = "/".join(parts)
        if include_side:
            return f"{placement} {self.side_to_move}"
        return placement

    def piece_at(self, sq: Square) -> str:
        return self.grid[9 - sq.rank][sq.file]

    def set_piece(self, sq: Square, piece: str) -> None:
        self.grid[9 - sq.rank][sq.file] = piece

    def flip(self) -> "Board":
        """上下左右翻转（棋子颜色不变），并交换行棋方。"""
        new_grid = [list(reversed(row)) for row in reversed(self.grid)]
        side = "b" if self.side_to_move == "w" else "w"
        return Board(new_grid, side)

    def apply_move(self, move: Move) -> "Board":
        nxt = self.copy()
        piece = nxt.piece_at(move.frm)
        if piece == ".":
            raise ValueError(f"起点无子: {move.uci}")
        nxt.set_piece(move.frm, ".")
        nxt.set_piece(move.to, piece)
        nxt.side_to_move = "b" if self.side_to_move == "w" else "w"
        return nxt

    def find_kings(self) -> tuple[Optional[Square], Optional[Square]]:
        red_k = black_k = None
        for rank in range(10):
            for file in range(9):
                sq = Square(file, rank)
                p = self.piece_at(sq)
                if p == "K":
                    red_k = sq
                elif p == "k":
                    black_k = sq
        return red_k, black_k

    def infer_red_at_bottom(self) -> bool:
        """当前布局是否红在下方（引擎标准视角）。"""
        red_k, black_k = self.find_kings()
        if red_k and black_k:
            return red_k.rank < black_k.rank
        if red_k:
            return red_k.rank <= 2
        if black_k:
            return black_k.rank >= 7
        return True

    def normalize_red_bottom(self) -> "Board":
        """返回红在下方的棋盘（仅空间翻转）。"""
        if self.infer_red_at_bottom():
            return self.copy()
        return self.flip()

    def normalize_to_engine_view(self) -> tuple["Board", bool]:
        if self.infer_red_at_bottom():
            return self.copy(), False
        return self.flip(), True

    def count_pieces(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.grid:
            for ch in row:
                if ch != ".":
                    counts[ch] = counts.get(ch, 0) + 1
        return counts

    def validate_piece_counts(self) -> list[str]:
        return validate_piece_counts(self)

    def diff_move(self, other: "Board") -> Optional[Move]:
        changed: list[tuple[Square, str, str]] = []
        for rank in range(10):
            for file in range(9):
                sq = Square(file, rank)
                a = self.piece_at(sq)
                b = other.piece_at(sq)
                if a != b:
                    changed.append((sq, a, b))
        if not changed:
            return None
        emptied = [c for c in changed if c[1] != "." and c[2] == "."]
        filled = [c for c in changed if c[2] != "." and c[1] != c[2]]
        if len(emptied) == 1 and len(filled) == 1:
            return Move(emptied[0][0], filled[0][0])
        return None

    def ascii(self) -> str:
        lines = ["  a b c d e f g h i"]
        for rank in range(9, -1, -1):
            cells = [self.piece_at(Square(f, rank)) for f in range(9)]
            lines.append(f"{rank} " + " ".join(cells))
        lines.append(f"side: {self.side_to_move}")
        return "\n".join(lines)

    def pretty(self) -> str:
        return self.ascii()


def placement_equal(a: Board, b: Board) -> bool:
    return a.grid == b.grid


def is_start_placement(board: Board) -> bool:
    """是否为红在下的标准开局摆子（不含行棋方）。"""
    return board.grid == Board.start().grid


def placement_diff_count(a: Board, b: Board) -> int:
    n = 0
    for r in range(10):
        for f in range(9):
            if a.grid[r][f] != b.grid[r][f]:
                n += 1
    return n


def start_agreement(board: Board) -> tuple[int, int, int, int]:
    """返回 (agree, occupied_start, missing, wrong_on_start)。"""
    start = Board.start()
    agree = occupied = missing = wrong = 0
    for sq in iter_squares():
        sp = start.piece_at(sq)
        if sp == ".":
            continue
        occupied += 1
        bp = board.piece_at(sq)
        if bp == sp:
            agree += 1
        elif bp == ".":
            missing += 1
        else:
            wrong += 1
    return agree, occupied, missing, wrong


# 模板匹配常见混淆（仅这些允许出现在「开局误识」里）
_START_MISREAD_PAIRS = {
    frozenset({"n", "r"}),
    frozenset({"N", "R"}),
    frozenset({"b", "n"}),
    frozenset({"B", "N"}),
}


def maybe_snap_start(board: Board, min_agree: int = 26) -> Board | None:
    """
    开局漏识边路车/马/炮时吸附到标准开局。
    若有子落在开局空位上（真实已行棋），绝不吸附。
    """
    start = Board.start()
    # 开局空位上出现棋子 → 已行棋
    for sq in iter_squares():
        if start.piece_at(sq) == "." and board.piece_at(sq) != ".":
            return None
    agree, occupied, missing, wrong = start_agreement(board)
    if occupied <= 0 or agree < min_agree:
        return None
    # 至少两处漏识/误识才吸附，避免把真实一手抹掉
    if missing + wrong < 2:
        return None
    # 误识格必须像模板混淆，不能是真实走子后的异种棋子
    for sq in iter_squares():
        sp = start.piece_at(sq)
        bp = board.piece_at(sq)
        if sp != "." and bp not in (".", sp):
            if frozenset({sp, bp}) not in _START_MISREAD_PAIRS:
                return None
    total = sum(board.count_pieces().values())
    if total < 28 or total > 32:
        return None
    if board.piece_at(Square(4, 0)) != "K" or board.piece_at(Square(4, 9)) != "k":
        return None
    out = Board.start()
    out.side_to_move = board.side_to_move
    return out


def validate_piece_counts(board: Board) -> list[str]:
    issues: list[str] = []
    counts = board.count_pieces()
    for ch, mx in EXPECTED_COUNTS.items():
        n = counts.get(ch, 0)
        if n > mx:
            issues.append(f"{ch} 数量过多: {n}>{mx}")
    if counts.get("K", 0) != 1:
        issues.append("缺少红帅" if counts.get("K", 0) == 0 else "红帅数量异常")
    if counts.get("k", 0) != 1:
        issues.append("缺少黑将" if counts.get("k", 0) == 0 else "黑将数量异常")
    return issues


def iter_squares() -> Iterable[Square]:
    for rank in range(10):
        for file in range(9):
            yield Square(file, rank)


def _file_num_zh(file: int, red: bool) -> str:
    n = (9 - file) if red else (file + 1)
    return _ZH_NUM[n - 1]


def describe_move_zh(board: Board, move: Move) -> str:
    """红在下的标准盘上，把着法写成中文代数记号（如 炮二平五）。"""
    piece = board.piece_at(move.frm)
    if piece == ".":
        return move.uci
    red = piece.isupper()
    name = PIECE_ZH_SHORT.get(piece, piece)
    same_file = [
        sq
        for sq in iter_squares()
        if board.piece_at(sq) == piece and sq.file == move.frm.file
    ]
    if len(same_file) >= 2:
        ordered = sorted(same_file, key=(lambda s: -s.rank) if red else (lambda s: s.rank))
        if len(ordered) == 2:
            tags = ("前", "后")
        elif len(ordered) == 3:
            tags = ("前", "中", "后")
        else:
            tags = ("前",) + ("中",) * (len(ordered) - 2) + ("后",)
        idx = next(i for i, sq in enumerate(ordered) if sq == move.frm)
        prefix = tags[idx] + name
    else:
        prefix = name + _file_num_zh(move.frm.file, red)

    frm, to = move.frm, move.to
    dest_file = _file_num_zh(to.file, red)
    if frm.rank == to.rank:
        return prefix + "平" + dest_file
    advancing = (to.rank > frm.rank) if red else (to.rank < frm.rank)
    verb = "进" if advancing else "退"
    kind = piece.upper()
    if kind in "RCPK" and frm.file == to.file:
        dest = _ZH_NUM[abs(to.rank - frm.rank) - 1]
    else:
        dest = dest_file
    return prefix + verb + dest
