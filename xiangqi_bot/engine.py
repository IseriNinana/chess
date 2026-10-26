"""Pikafish UCI 引擎封装。"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from .board import Board, Move


class EngineError(RuntimeError):
    pass


class PikafishEngine:
    def __init__(
        self,
        path: str | Path,
        nnue: str | Path | None = None,
        threads: int = 4,
        hash_mb: int = 128,
        movetime_ms: int = 800,
        depth: int = 0,
    ):
        self.exe_path = Path(path)
        self.nnue_path = Path(nnue) if nnue else None
        self.threads = threads
        self.hash_mb = hash_mb
        self.movetime_ms = movetime_ms
        self.depth = depth
        self._proc: Optional[subprocess.Popen[str]] = None
        self._lock = threading.Lock()
        self._reader_thread: Optional[threading.Thread] = None
        self._lines: list[str] = []
        self._line_event = threading.Event()

    def start(self) -> None:
        if not self.exe_path.exists():
            raise EngineError(
                f"找不到引擎: {self.exe_path}\n"
                "请先运行: python main.py download"
            )
        cwd = str(self.exe_path.parent)
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

        self._proc = subprocess.Popen(
            [str(self.exe_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=cwd,
            creationflags=creationflags,
        )
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

        self._send("uci")
        self._wait_for("uciok", timeout=10)

        if self.nnue_path and self.nnue_path.exists():
            self._send(f"setoption name EvalFile value {self.nnue_path.name}")

        self._send(f"setoption name Threads value {self.threads}")
        self._send(f"setoption name Hash value {self.hash_mb}")
        self._send("isready")
        self._wait_for("readyok", timeout=30)

    def new_game(self) -> None:
        self._send("ucinewgame")
        self._send("isready")
        self._wait_for("readyok", timeout=30)

    def stop(self) -> None:
        self.close()

    def close(self) -> None:
        if not self._proc:
            return
        try:
            self._send("quit")
            self._proc.wait(timeout=2)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None

    def __enter__(self) -> "PikafishEngine":
        self.start()
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            with self._lock:
                self._lines.append(line)
            self._line_event.set()

    def _send(self, cmd: str) -> None:
        if not self._proc or not self._proc.stdin:
            raise EngineError("引擎未启动")
        self._proc.stdin.write(cmd + "\n")
        self._proc.stdin.flush()

    def _drain(self) -> list[str]:
        with self._lock:
            lines = self._lines[:]
            self._lines.clear()
        return lines

    def _wait_for(self, token: str, timeout: float = 10.0) -> list[str]:
        deadline = time.time() + timeout
        collected: list[str] = []
        while time.time() < deadline:
            self._line_event.wait(timeout=0.05)
            self._line_event.clear()
            batch = self._drain()
            collected.extend(batch)
            if any(token in ln for ln in batch):
                return collected
        raise EngineError(f"等待 '{token}' 超时。已收到: {collected[-5:]}")

    def best_move(
        self,
        board: Board,
        movetime_ms: int | None = None,
        depth: int | None = None,
        moves: Optional[list[Move]] = None,
    ) -> Move:
        fen = board.to_fen(include_side=True)
        cmd = f"position fen {fen}"
        if moves:
            cmd += " moves " + " ".join(m.uci for m in moves)
        self._send(cmd)

        use_depth = self.depth if depth is None else depth
        use_time = self.movetime_ms if movetime_ms is None else movetime_ms

        if use_depth and use_depth > 0:
            self._send(f"go depth {use_depth}")
            timeout = max(30.0, use_depth * 2.0)
        else:
            self._send(f"go movetime {use_time}")
            timeout = max(5.0, use_time / 1000.0 + 3.0)

        lines = self._wait_for("bestmove", timeout=timeout)
        for ln in reversed(lines):
            if ln.startswith("bestmove"):
                parts = ln.split()
                if len(parts) < 2 or parts[1] == "(none)":
                    raise EngineError(f"引擎无着法: {ln}")
                return Move.from_uci(parts[1])
        raise EngineError("未解析到 bestmove")

    def analyse(self, board: Board, movetime_ms: int = 1000) -> dict:
        fen = board.to_fen(include_side=True)
        self._send(f"position fen {fen}")
        self._send(f"go movetime {movetime_ms}")
        timeout = max(5.0, movetime_ms / 1000.0 + 3.0)
        lines = self._wait_for("bestmove", timeout=timeout)

        info = ""
        best = ""
        score_cp = None
        for ln in lines:
            if ln.startswith("info "):
                info = ln
                parts = ln.split()
                if "score" in parts:
                    i = parts.index("score")
                    if i + 2 < len(parts) and parts[i + 1] == "cp":
                        try:
                            score_cp = int(parts[i + 2])
                        except ValueError:
                            pass
                    elif i + 2 < len(parts) and parts[i + 1] == "mate":
                        try:
                            mate = int(parts[i + 2])
                            score_cp = 100000 if mate > 0 else -100000
                        except ValueError:
                            pass
            if ln.startswith("bestmove"):
                best = ln.split()[1]

        if not best or best == "(none)":
            raise EngineError(f"引擎无着法: {lines[-3:]}")
        return {
            "move": Move.from_uci(best),
            "bestmove": best,
            "score_cp": score_cp,
            "info": info,
            "fen": fen,
        }

    # 兼容旧拼写
    analyze = analyse
