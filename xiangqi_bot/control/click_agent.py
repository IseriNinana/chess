"""独立点击进程：跑在 Cursor Job 之外，用真实 SendInput 点屏幕。

协议（TCP 127.0.0.1，端口写在 %TEMP%/xiangqi_bot_click_agent.json）：
  CLICK x y
  DRAG x0 y0 x1 y1 duration
  PING
  QUIT
回复一行 OK / ERR ...
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

STATE_PATH = Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".") / "xiangqi_bot_click_agent.json"
HOST = "127.0.0.1"
LAUNCHER_CMD = Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".") / "xiangqi_bot_click_agent_launch.cmd"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import ctypes

        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
    except Exception:
        pass
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_state() -> dict | None:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    pid = int(data.get("pid") or 0)
    port = int(data.get("port") or 0)
    if not pid or not port or not _pid_alive(pid):
        return None
    return data


def _send(port: int, line: str, timeout: float = 3.0) -> str:
    with socket.create_connection((HOST, port), timeout=timeout) as sock:
        sock.sendall((line.strip() + "\n").encode("utf-8"))
        sock.settimeout(timeout)
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(256)
            if not chunk:
                break
            buf += chunk
    return buf.decode("utf-8", errors="replace").strip()


def ping(port: int) -> bool:
    try:
        return _send(port, "PING") == "OK"
    except OSError:
        return False


def serve() -> None:
    from .mouse import enable_dpi_awareness, send_click_at, send_drag_at

    enable_dpi_awareness()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((HOST, 0))
    sock.listen(8)
    port = int(sock.getsockname()[1])
    STATE_PATH.write_text(
        json.dumps({"pid": os.getpid(), "port": port}, ensure_ascii=False),
        encoding="utf-8",
    )
    while True:
        conn, _addr = sock.accept()
        try:
            data = b""
            conn.settimeout(5)
            while b"\n" not in data:
                chunk = conn.recv(256)
                if not chunk:
                    break
                data += chunk
            line = data.decode("utf-8", errors="replace").strip()
            parts = line.split()
            cmd = parts[0].upper() if parts else ""
            if cmd == "PING":
                conn.sendall(b"OK\n")
            elif cmd == "QUIT":
                conn.sendall(b"OK\n")
                return
            elif cmd == "CLICK" and len(parts) >= 3:
                send_click_at(int(parts[1]), int(parts[2]))
                conn.sendall(b"OK\n")
            elif cmd == "DRAG" and len(parts) >= 5:
                dur = float(parts[5]) if len(parts) >= 6 else 0.12
                send_drag_at(int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4]), dur)
                conn.sendall(b"OK\n")
            else:
                conn.sendall(b"ERR unknown\n")
        except Exception as exc:
            try:
                conn.sendall(f"ERR {exc}\n".encode("utf-8"))
            except OSError:
                pass
        finally:
            try:
                conn.close()
            except OSError:
                pass


def _write_launcher() -> Path:
    root = _project_root()
    py = Path(sys.executable)
    lines = [
        "@echo off",
        f'cd /d "{root}"',
        "set PYTHONUNBUFFERED=1",
        f'set PYTHONPATH={root}',
        f'"{py}" -u -m xiangqi_bot.control.click_agent',
    ]
    LAUNCHER_CMD.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return LAUNCHER_CMD


def _spawn_breakaway() -> None:
    CREATE_BREAKAWAY_FROM_JOB = 0x01000000
    CREATE_NEW_CONSOLE = 0x00000010
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    DETACHED_PROCESS = 0x00000008
    root = str(_project_root())
    flags = CREATE_BREAKAWAY_FROM_JOB | CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
    try:
        subprocess.Popen(
            [sys.executable, "-u", "-m", "xiangqi_bot.control.click_agent"],
            cwd=root,
            env={**os.environ, "PYTHONPATH": root, "PYTHONUNBUFFERED": "1"},
            creationflags=flags,
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    except OSError:
        pass
    try:
        subprocess.Popen(
            [sys.executable, "-u", "-m", "xiangqi_bot.control.click_agent"],
            cwd=root,
            env={**os.environ, "PYTHONPATH": root, "PYTHONUNBUFFERED": "1"},
            creationflags=CREATE_NEW_CONSOLE | CREATE_BREAKAWAY_FROM_JOB,
            close_fds=True,
        )
    except OSError:
        pass


def _spawn_wmi() -> None:
    launcher = _write_launcher()
    cmd = f'cmd.exe /c "{launcher}"'
    # WMI 创建的进程通常不在 Cursor Job 里
    ps = (
        "$s = ([wmiclass]'Win32_ProcessStartup').CreateInstance(); "
        "$s.ShowWindow = 0; "
        f"$r = ([wmiclass]'Win32_Process').Create('{cmd.replace(chr(39), chr(39)+chr(39))}', "
        f"'{str(_project_root()).replace(chr(39), chr(39)+chr(39))}', $s); "
        "if ($r.ReturnValue -ne 0) { exit $r.ReturnValue }"
    )
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            ps,
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def _spawn_explorer() -> None:
    launcher = _write_launcher()
    try:
        os.startfile(str(launcher))  # type: ignore[attr-defined]
        return
    except OSError:
        pass
    subprocess.Popen(["explorer.exe", str(launcher)], close_fds=True)


def start_agent() -> dict | None:
    state = _read_state()
    if state and ping(int(state["port"])):
        return state
    _spawn_breakaway()
    deadline = time.time() + 2.5
    while time.time() < deadline:
        state = _read_state()
        if state and ping(int(state["port"])):
            return state
        time.sleep(0.15)
    _spawn_wmi()
    deadline = time.time() + 4.0
    while time.time() < deadline:
        state = _read_state()
        if state and ping(int(state["port"])):
            return state
        time.sleep(0.2)
    _spawn_explorer()
    deadline = time.time() + 4.0
    while time.time() < deadline:
        state = _read_state()
        if state and ping(int(state["port"])):
            return state
        time.sleep(0.2)
    state = _read_state()
    if state and ping(int(state["port"])):
        return state
    return None


class ClickAgentClient:
    def __init__(self) -> None:
        self.port: int | None = None
        self.pid: int | None = None

    def ensure(self) -> bool:
        state = start_agent()
        if not state:
            return False
        self.port = int(state["port"])
        self.pid = int(state["pid"])
        return ping(self.port)

    def click(self, x: int, y: int) -> bool:
        if self.port is None and not self.ensure():
            return False
        try:
            return _send(int(self.port), f"CLICK {int(x)} {int(y)}") == "OK"
        except OSError:
            if self.ensure():
                try:
                    return _send(int(self.port), f"CLICK {int(x)} {int(y)}") == "OK"
                except OSError:
                    return False
            return False

    def drag(self, x0: int, y0: int, x1: int, y1: int, duration: float = 0.12) -> bool:
        if self.port is None and not self.ensure():
            return False
        line = f"DRAG {int(x0)} {int(y0)} {int(x1)} {int(y1)} {float(duration)}"
        try:
            return _send(int(self.port), line, timeout=5.0) == "OK"
        except OSError:
            return False


def main() -> None:
    serve()


if __name__ == "__main__":
    main()
