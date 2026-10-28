"""棋盘 / FEN 基础自检。"""

from xiangqi_bot.board import (
    START_FEN,
    Board,
    Move,
    Square,
    describe_move_zh,
    is_start_placement,
    placement_diff_count,
)


def test_start_fen_roundtrip():
    b = Board.from_fen(START_FEN)
    assert b.piece_at(Square(0, 0)) == "R"
    assert b.piece_at(Square(4, 0)) == "K"
    assert b.piece_at(Square(4, 9)) == "k"
    fen = b.to_fen()
    assert fen.startswith("rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR")
    b2 = Board.from_fen(fen)
    assert b == b2


def test_move_and_flip():
    b = Board.start()
    m = Move.from_uci("h2e2")
    assert m.uci == "h2e2"
    nxt = b.apply_move(m)
    assert nxt.piece_at(Square(7, 2)) == "."
    assert nxt.piece_at(Square(4, 2)) == "C"
    assert nxt.side_to_move == "b"

    flipped = b.flip()
    # 空间翻转：原 (4,0) 红帅 -> (4,9)，颜色不变
    assert flipped.piece_at(Square(4, 9)) == "K"
    assert flipped.piece_at(Square(4, 0)) == "k"


def test_describe_move_zh():
    b = Board.start()
    assert describe_move_zh(b, Move.from_uci("h2e2")) == "炮二平五"
    assert describe_move_zh(b, Move.from_uci("b0c2")) == "马八进七"
    b2 = b.apply_move(Move.from_uci("h2e2"))
    assert describe_move_zh(b2, Move.from_uci("b7e7")) == "炮二平五"


def test_start_placement():
    b = Board.start()
    assert is_start_placement(b)
    nxt = b.apply_move(Move.from_uci("b2e2"))
    assert not is_start_placement(nxt)
    assert placement_diff_count(b, nxt) == 2


if __name__ == "__main__":
    test_start_fen_roundtrip()
    test_move_and_flip()
    test_describe_move_zh()
    test_start_placement()
    print("ok")
