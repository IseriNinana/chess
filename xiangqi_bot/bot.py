"""自动下棋主循环。"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from .board import Board, Move, Square, maybe_snap_start, placement_equal
from .control.mouse import MouseController, enable_dpi_awareness
from .engine import PikafishEngine
from .vision.calibrate import load_or_calibrate
from .vision.capture import ScreenCapture
from .vision.detect import annotate_board
from .vision.factory import make_detector


class XiangqiBot:
    def __init__(self, cfg: dict):
        enable_dpi_awareness()
        self.cfg = cfg
        self.paused = False
        self._stop = False

        eng = cfg["engine"]
        self.engine = PikafishEngine(
            path=eng["path"],
            nnue=eng.get("nnue"),
            threads=int(eng.get("threads", 4)),
            hash_mb=int(eng.get("hash_mb", 128)),
            movetime_ms=int(eng.get("movetime_ms", 800)),
            depth=int(eng.get("depth", 0)),
        )

        vis = cfg["vision"]
        self.calib = load_or_calibrate(vis["calib_file"], cfg["screen"].get("monitor", 1))
        self.detector = make_detector(vis)
        if not self.detector.ready:
            raise RuntimeError(
                "棋子识别器未就绪。template 请先 templates；cnn 请先 collect-cls + train-cls"
            )
        backend = str(vis.get("backend", "template"))
        print(f"识别后端: {backend}", flush=True)
        self.reshoot_delay = float(vis.get("reshoot_delay", 0.25))

        self.cap = ScreenCapture(cfg["screen"].get("monitor", 1))
        mouse_cfg = cfg.get("mouse", {})
        hwnd = None
        try:
            from .vision.window import find_xiangqi_window

            win = find_xiangqi_window()
            if win:
                hwnd = win.hwnd
        except Exception:
            pass
        self.mouse = MouseController(
            self.calib.region,
            dpi_scale=float(cfg["screen"].get("dpi_scale", 1.0)),
            move_duration=float(mouse_cfg.get("move_duration", 0.12)),
            click_interval=float(mouse_cfg.get("click_interval", 0.25)),
            pad_y_cells=float(getattr(self.calib, "pad_y_cells", 0.5)),
            pad_x_cells=float(getattr(self.calib, "pad_x_cells", 0.5)),
            mode=str(mouse_cfg.get("mode", "both")),
            hwnd=hwnd,
        )
        self.after_move_wait = float(mouse_cfg.get("after_move_wait", 0.8))

        bot = cfg.get("bot", {})
        self.side_pref = str(bot.get("side", "auto")).lower()
        self.poll_interval = float(bot.get("poll_interval", 0.35))
        self.hotkey_pause = bot.get("hotkey_pause", "f8")
        self.hotkey_quit = bot.get("hotkey_quit", "f9")
        debug = bot.get("debug_dir") or ""
        self.debug_dir = Path(debug) if debug else None
        if self.debug_dir:
            self.debug_dir.mkdir(parents=True, exist_ok=True)

        self.our_side: str | None = None  # 'w' or 'b'
        self.last_board: Board | None = None
        self.last_played: Move | None = None
        self._repeat_guard: Move | None = None
        self._last_frame: np.ndarray | None = None
        self._ref_frame: np.ndarray | None = None

    def close(self) -> None:
        self.engine.stop()
        self.cap.close()

    def _bind_hotkeys(self) -> None:
        try:
            import keyboard

            keyboard.add_hotkey(self.hotkey_pause, self._toggle_pause)
            keyboard.add_hotkey(self.hotkey_quit, self._request_stop)
        except Exception as exc:
            print(f"热键不可用（可忽略）: {exc}")
            print("可用 Ctrl+C 退出。")

    def _toggle_pause(self) -> None:
        self.paused = not self.paused
        print(f"[{'暂停' if self.paused else '继续'}]")

    def _request_stop(self) -> None:
        self._stop = True
        print("[退出请求]")

    def recognize(self) -> tuple[Board, list]:
        """多次截图按格投票，提高稳定性。"""
        shots = []
        for i in range(3):
            img = self.cap.grab_region(self.calib.region)
            board, guesses = self.detector.detect_board(img, self.calib, side_to_move="w")
            shots.append((img, board, guesses))
            if i < 2:
                time.sleep(self.reshoot_delay)

        # 逐格：选出现次数最多的棋子；平票取最高分
        from collections import defaultdict

        vote: dict[Square, list[tuple[str, float]]] = defaultdict(list)
        for _, _, guesses in shots:
            for g in guesses:
                vote[g.square].append((g.piece, g.score))

        merged = Board.empty()
        merged_guesses = []
        for sq, items in vote.items():
            tally: dict[str, list[float]] = defaultdict(list)
            for piece, score in items:
                tally[piece].append(score)
            best_piece = max(
                tally.items(),
                key=lambda kv: (len(kv[1]), sum(kv[1]) / len(kv[1])),
            )[0]
            best_score = max(tally[best_piece])
            merged.set_piece(sq, best_piece)
            from .vision.detect import CellGuess

            merged_guesses.append(CellGuess(sq, best_piece, best_score))

        # 数量修正
        merged = self.detector._maybe_fix_counts(merged, merged_guesses)
        img = shots[-1][0]
        self._last_frame = img

        if not merged.infer_red_at_bottom():
            merged = merged.flip()

        # 开局漏识边路车/马/炮时吸附到标准开局，避免引擎走出非法/瞎着
        snapped = maybe_snap_start(merged)
        if snapped is not None:
            print(
                f"识别接近开局（已吸附标准开局，原 FEN={merged.to_fen(include_side=False)}）",
                flush=True,
            )
            merged = snapped

        print("识别棋盘:", flush=True)
        print(merged.pretty(), flush=True)
        print(f"FEN: {merged.to_fen()}", flush=True)

        if self.debug_dir:
            vis = annotate_board(img, self.calib, merged, merged_guesses)
            cv2.imencode(".png", vis)[1].tofile(str(self.debug_dir / "last_board.png"))
        return merged, merged_guesses

    def _frame_mean_diff(self, a: np.ndarray, b: np.ndarray) -> float:
        if a is None or b is None or a.shape != b.shape:
            return 999.0
        ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32)
        gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32)
        return float(np.mean(np.abs(ga - gb)))

    def _visually_changed_squares(
        self,
        prev: np.ndarray,
        curr: np.ndarray,
        cell_thresh: float = 16.0,
    ) -> list[Square]:
        """找出像素变化明显的交叉点（对手走子时 FEN 常不变）。"""
        if prev is None or curr is None or prev.shape != curr.shape:
            return []
        changed: list[Square] = []
        for sq in (
            Square(f, r) for r in range(10) for f in range(9)
        ):
            ra = self.calib.cell_roi(prev, sq, scale=0.8)
            rb = self.calib.cell_roi(curr, sq, scale=0.8)
            if ra.size == 0 or rb.size == 0 or ra.shape != rb.shape:
                continue
            ga = cv2.cvtColor(ra, cv2.COLOR_BGR2GRAY).astype(np.float32)
            gb = cv2.cvtColor(rb, cv2.COLOR_BGR2GRAY).astype(np.float32)
            if float(np.mean(np.abs(ga - gb))) >= cell_thresh:
                changed.append(sq)
        # 排除我方刚走的起终格（残留高亮）
        if self.last_played:
            ignore = {self.last_played.frm, self.last_played.to}
            changed = [sq for sq in changed if sq not in ignore]
        return changed

    def _relabel_changed(
        self,
        img: np.ndarray,
        board: Board,
        squares: list[Square],
    ) -> Board:
        """对画面变化的格子强制重识别（不依赖墨迹门控）。"""
        out = board.copy()
        for sq in squares:
            roi = self.calib.cell_roi(img, sq, scale=0.9)
            piece, score = self.detector.classify_roi(roi, force=True)
            if score >= self.detector.empty_threshold * 0.7 or piece != ".":
                out.set_piece(sq, piece)
        return out

    def resolve_our_side(self, board: Board) -> str:
        _ = board
        if self.side_pref in ("red", "w", "white"):
            return "w"
        if self.side_pref in ("black", "b"):
            return "b"
        return self._raw_board_side_at_bottom()

    def _raw_board_side_at_bottom(self) -> str:
        """屏幕下方棋子颜色 ≈ 我方（天天象棋通常自己在下）。"""
        img = self.cap.grab_region(self.calib.region)
        board, _ = self.detector.detect_board(img, self.calib)
        red = black = 0
        for rank in range(0, 5):  # rank0 在截图底部
            for file in range(9):
                p = board.piece_at(Square(file, rank))
                if p in "RNBAKCP":
                    red += 1
                elif p in "rnbakcp":
                    black += 1
        return "w" if red >= black else "b"

    def run(self) -> None:
        print("启动 Pikafish…")
        self.engine.start()
        self.engine.new_game()
        self._bind_hotkeys()
        print(f"热键: {self.hotkey_pause}=暂停/继续  {self.hotkey_quit}=退出")
        print("请切换到象棋窗口，确保棋盘完整可见。")

        board, _ = self.recognize()
        if not self._board_usable(board):
            print("初始识别失败（空盘/缺将帅），请确保棋盘完整可见后重试")
            self.close()
            return
        self.our_side = self.resolve_our_side(board)
        print(f"我方: {'红' if self.our_side == 'w' else '黑'}")
        board.side_to_move = self.our_side
        self.last_board = board

        if self._is_our_turn(board):
            self._play_until_opponent_turn(board)

        waiting_since = time.time()
        last_beat = 0.0
        stable_pending: Board | None = None
        stable_hits = 0
        print("等待对手出招…（看到对方走子后会自动接走）")

        while not self._stop:
            if self.paused:
                time.sleep(0.2)
                continue
            try:
                board, _ = self.recognize()
            except Exception as exc:
                print(f"识别失败: {exc}", flush=True)
                time.sleep(self.poll_interval)
                continue

            # 动画/闪帧常识别成空盘，直接忽略
            if not self._board_usable(board):
                now = time.time()
                if now - last_beat >= 4.0:
                    print("识别不稳定（动画/遮挡），继续监控…", flush=True)
                    last_beat = now
                time.sleep(self.poll_interval)
                continue

            if self.last_board is None:
                self.last_board = board
                time.sleep(self.poll_interval)
                continue

            if placement_equal(board, self.last_board):
                stable_pending = None
                stable_hits = 0

                # FEN 不变但画面变了 → 对手已走、识别漏子（常见于黑马/黑卒）
                forced = False
                wait_s = time.time() - waiting_since
                if (
                    self._ref_frame is not None
                    and self._last_frame is not None
                    and wait_s >= 1.0
                ):
                    mean_d = self._frame_mean_diff(self._ref_frame, self._last_frame)
                    # 黑卒移动像素差较小，等待稍久后降低阈值
                    cell_thr = 10.0 if wait_s >= 4.0 else 14.0
                    changed = self._visually_changed_squares(
                        self._ref_frame, self._last_frame, cell_thresh=cell_thr
                    )
                    if not changed and mean_d >= 2.0:
                        changed = self._visually_changed_squares(
                            self._ref_frame, self._last_frame, cell_thresh=8.0
                        )

                    if changed:
                        patched = self._relabel_changed(
                            self._last_frame, board, changed
                        )
                        if not placement_equal(patched, self.last_board):
                            board = patched
                            board.side_to_move = self.our_side or "w"
                            print(
                                f"画面变化格子 {[s.uci for s in changed]} → "
                                f"重识别 FEN={board.to_fen(include_side=False)}",
                                flush=True,
                            )
                            self.last_board = board
                            self._play_until_opponent_turn(board)
                            waiting_since = time.time()
                            last_beat = 0.0
                            print("等待对手出招…", flush=True)
                            forced = True

                    if not forced and (
                        (len(changed) >= 1 and (mean_d >= 1.8 or wait_s >= 5.0))
                        or mean_d >= 4.5
                    ):
                        print(
                            f"画面有变化(diff={mean_d:.1f}, cells="
                            f"{[s.uci for s in changed]}) 但 FEN 仍相同 → "
                            "按对方已走、强制我方续走",
                            flush=True,
                        )
                        board.side_to_move = self.our_side or "w"
                        self._play_until_opponent_turn(board)
                        waiting_since = time.time()
                        last_beat = 0.0
                        print("等待对手出招…", flush=True)
                        forced = True

                if forced:
                    time.sleep(self.poll_interval)
                    continue

                now = time.time()
                if now - last_beat >= 4.0:
                    elapsed = int(now - waiting_since)
                    diff_s = ""
                    if self._ref_frame is not None and self._last_frame is not None:
                        diff_s = f"  screen_diff={self._frame_mean_diff(self._ref_frame, self._last_frame):.1f}"
                    print(
                        f"等待对手中…已 {elapsed}s  FEN={board.to_fen(include_side=False)}{diff_s}",
                        flush=True,
                    )
                    last_beat = now
                time.sleep(self.poll_interval)
                continue

            # 局面有变化：连续两次相同再采纳，避免识别闪烁误触发
            if stable_pending is not None and placement_equal(board, stable_pending):
                stable_hits += 1
            else:
                stable_pending = board
                stable_hits = 1
            if stable_hits < 2:
                time.sleep(self.poll_interval)
                continue

            board.side_to_move = self._infer_side_to_move(self.last_board, board)
            mv = self.last_board.diff_move(board)
            print(
                f"局面变化 -> FEN: {board.to_fen()}"
                + (f"  (检测到着法 {mv.uci})" if mv else ""),
                flush=True,
            )
            self.last_board = board
            self._repeat_guard = None
            stable_pending = None
            stable_hits = 0

            if self._is_our_turn(board):
                self._play_until_opponent_turn(board)
                waiting_since = time.time()
                last_beat = 0.0
                print("等待对手出招…", flush=True)
            else:
                waiting_since = time.time()
                self._snapshot_ref_frame()
                print("仍是对方行棋，继续等待…", flush=True)

            time.sleep(self.poll_interval)

        self.close()
        print("已退出")

    def _play_until_opponent_turn(self, board: Board) -> None:
        """走我方棋；若确认阶段对手已应着，则连续再走。

        连续接走有上限，避免一次爆发过多；触顶后冷却再续走，
        绝不能在「仍是我方行棋」时丢进等待监控（否则 FEN 不变会永久卡住）。
        """
        current = board
        burst = 0
        hand = 1
        announce_continue = False
        while not self._stop and self._is_our_turn(current):
            if burst >= 20:
                print("连续接走过快，冷却后继续…", flush=True)
                time.sleep(1.5)
                burst = 0
                if self.last_board is not None:
                    current = self.last_board
                    current.side_to_move = self.our_side or current.side_to_move
                continue
            if announce_continue:
                print(f"对手已应着，继续第 {hand} 手…", flush=True)
                announce_continue = False
            again = self._think_and_move(current)
            burst += 1
            if self.last_board is None:
                break
            current = self.last_board
            # 着法未生效：仍是我方则稍后重试，勿进等待监控
            if not again:
                if self._is_our_turn(current):
                    print("着法未确认，稍后重试…", flush=True)
                    time.sleep(0.8)
                    continue
                break
            hand += 1
            announce_continue = True
            current.side_to_move = self.our_side or current.side_to_move
        self._snapshot_ref_frame()

    def _snapshot_ref_frame(self) -> None:
        """走子后保存参考帧，用于检测对手画面变化。"""
        time.sleep(0.35)
        try:
            self._ref_frame = self.cap.grab_region(self.calib.region)
            self._last_frame = self._ref_frame
        except Exception:
            if self._last_frame is not None:
                self._ref_frame = self._last_frame.copy()

    @staticmethod
    def _board_usable(board: Board) -> bool:
        """过滤空盘、缺将帅等无效识别。"""
        counts = board.count_pieces()
        if sum(counts.values()) < 8:
            return False
        if counts.get("K", 0) != 1 or counts.get("k", 0) != 1:
            return False
        return True

    def _infer_side_to_move(self, before: Board, after: Board) -> str:
        moved_color = None
        for rank in range(10):
            for file in range(9):
                sq = Square(file, rank)
                p0 = before.piece_at(sq)
                p1 = after.piece_at(sq)
                if p0 != "." and p1 == ".":
                    moved_color = "w" if p0.isupper() else "b"
                    break
            if moved_color:
                break
        if moved_color == "w":
            return "b"
        if moved_color == "b":
            return "w"
        return self.our_side or "w"

    def _is_our_turn(self, board: Board) -> bool:
        return board.side_to_move == self.our_side

    def _our_move_landed(self, before: Board, move: Move, confirmed: Board) -> bool:
        """确认画面是否表明我方该着已离开起点（未走成则绝不能按预期修正）。"""
        mover = before.piece_at(move.frm)
        if mover == ".":
            return False
        at_from = confirmed.piece_at(move.frm)
        at_to = confirmed.piece_at(move.to)
        # 起点仍是原棋子 → 点击未生效（如日志里 e2 炮未动）
        if at_from == mover:
            return False
        if at_to == mover:
            return True
        our = "RNBAKCP" if mover.isupper() else "rnbakcp"
        if at_to in our:
            return True
        # 起点已空：允许落点偶发漏识别
        return at_from == "."

    def _looks_like_opponent_reply(self, expected: Board, confirmed: Board) -> bool:
        """确认图相对「我方应走后局面」是否像对方又走了一步（排除识别噪点）。"""
        if placement_equal(expected, confirmed):
            return False
        opp_chars = set("rnbakcp") if self.our_side == "w" else set("RNBAKCP")
        diffs: list[tuple[Square, str, str]] = []
        for rank in range(10):
            for file in range(9):
                sq = Square(file, rank)
                e = expected.piece_at(sq)
                c = confirmed.piece_at(sq)
                if e != c:
                    diffs.append((sq, e, c))
        if not diffs or len(diffs) > 6:
            return False
        opp_hits = 0
        for _, e, c in diffs:
            if e in opp_chars or c in opp_chars:
                opp_hits += 1
        if opp_hits >= 1:
            return True
        mv = expected.diff_move(confirmed)
        if mv is not None:
            p = confirmed.piece_at(mv.to)
            if p in opp_chars:
                return True
        return False

    def _think_and_move(self, board: Board) -> bool:
        """走一步。返回 True 表示确认画面上对手已应着，应立即再走。"""
        assert self.our_side is not None
        if not self._board_usable(board):
            print("识别不可靠，跳过本步", flush=True)
            return False
        engine_board = board.normalize_red_bottom()
        engine_board.side_to_move = board.side_to_move
        print("引擎思考中…", engine_board.to_fen(), flush=True)
        try:
            move = self.engine.best_move(engine_board)
        except Exception as exc:
            print(f"引擎错误: {exc}", flush=True)
            return False

        print(f"着法: {move.uci}", flush=True)
        expected = None
        try:
            expected = board.apply_move(move)
        except Exception:
            expected = None

        try:
            from .vision.window import bring_to_front, find_xiangqi_window

            win = find_xiangqi_window()
            if win:
                self.mouse.hwnd = win.hwnd
                bring_to_front(win.hwnd)
                time.sleep(0.25)
        except Exception:
            pass

        self.mouse.play_move(move)
        self.last_played = move
        time.sleep(max(self.after_move_wait, 1.2))
        confirmed = None
        for _ in range(5):
            try:
                after, _ = self.recognize()
            except Exception:
                time.sleep(0.3)
                continue
            if not self._board_usable(after):
                time.sleep(0.3)
                continue
            if not placement_equal(after, board):
                confirmed = after
                break
            time.sleep(0.3)

        opp_side = "b" if self.our_side == "w" else "w"
        if confirmed is not None:
            landed = expected is not None and self._our_move_landed(
                board, move, confirmed
            )
            if not landed:
                # 局面有噪点变化但着法未落地 → 绝不能写成预期局面
                board.side_to_move = self.our_side
                self.last_board = board
                print(
                    f"警告: 着法 {move.uci} 未生效（起点仍有子或落点不符），"
                    f"不按预期修正",
                    flush=True,
                )
                return False
            if self._looks_like_opponent_reply(expected, confirmed):
                confirmed.side_to_move = self.our_side
                self.last_board = confirmed
                print(f"走后确认(对手已应着): {confirmed.to_fen()}", flush=True)
                return True
            # 已落地；识别噪点 → 采用预期局面
            expected.side_to_move = opp_side
            self.last_board = expected
            if placement_equal(confirmed, expected):
                print(f"走后确认: {expected.to_fen()}", flush=True)
            else:
                print(
                    f"走后确认: {expected.to_fen()} "
                    f"(识别有噪点，已按预期着法修正)",
                    flush=True,
                )
            return False
        # 不乐观改盘，避免空盘/未落子导致反复同一手
        board.side_to_move = self.our_side
        self.last_board = board
        print(
            "警告: 点击后局面无变化，可能坐标偏移。可调 config.yaml 里 screen.dpi_scale",
            flush=True,
        )
        return False
