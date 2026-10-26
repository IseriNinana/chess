"""鼠标控制：支持真实鼠标点击/拖拽，以及对窗口 PostMessage（部分游戏更吃这套）。"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from ..board import Move, Square
from ..vision.capture import Region

user32 = ctypes.windll.user32

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
INPUT_MOUSE = 0

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200
MK_LBUTTON = 0x0001


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]

    _anonymous_ = ("i",)
    _fields_ = [("type", wintypes.DWORD), ("i", _I)]


def enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


enable_dpi_awareness()


def _send_input_move_abs(x: int, y: int) -> None:
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    ax = int(x * 65535 / max(sw - 1, 1))
    ay = int(y * 65535 / max(sh - 1, 1))
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi = MOUSEINPUT(ax, ay, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _send_input_click() -> None:
    down = INPUT()
    down.type = INPUT_MOUSE
    down.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, None)
    up = INPUT()
    up.type = INPUT_MOUSE
    up.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, None)
    user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
    time.sleep(0.04)
    user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))


def _lparam(x: int, y: int) -> int:
    return (y << 16) | (x & 0xFFFF)


def _screen_to_client(hwnd: int, x: int, y: int) -> tuple[int, int]:
    pt = wintypes.POINT(x, y)
    user32.ScreenToClient(hwnd, ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def _window_from_point(x: int, y: int) -> int:
    return int(user32.WindowFromPoint(wintypes.POINT(x, y)))


def post_click_screen(x: int, y: int, hwnd: int | None = None) -> None:
    """向命中窗口发送客户区点击消息。"""
    target = hwnd or _window_from_point(x, y)
    if not target:
        return
    cx, cy = _screen_to_client(target, x, y)
    user32.SendMessageW(target, WM_MOUSEMOVE, 0, _lparam(cx, cy))
    user32.SendMessageW(target, WM_LBUTTONDOWN, MK_LBUTTON, _lparam(cx, cy))
    time.sleep(0.05)
    user32.SendMessageW(target, WM_LBUTTONUP, 0, _lparam(cx, cy))
    # 再对顶级窗口补一次（有的棋软只听父窗口）
    root = int(user32.GetAncestor(target, 2)) if target else 0  # GA_ROOT=2
    if root and root != target:
        cx2, cy2 = _screen_to_client(root, x, y)
        user32.SendMessageW(root, WM_LBUTTONDOWN, MK_LBUTTON, _lparam(cx2, cy2))
        time.sleep(0.03)
        user32.SendMessageW(root, WM_LBUTTONUP, 0, _lparam(cx2, cy2))


class MouseController:
    def __init__(
        self,
        board_region: Region,
        dpi_scale: float = 1.0,
        move_duration: float = 0.12,
        click_interval: float = 0.25,
        pad_y_cells: float = 0.5,
        pad_x_cells: float = 0.5,
        mode: str = "both",  # click | drag | postmessage | both
        hwnd: int | None = None,
    ):
        self.region = board_region
        self.dpi_scale = dpi_scale or 1.0
        self.move_duration = move_duration
        self.click_interval = click_interval
        self.pad_y_cells = pad_y_cells
        self.pad_x_cells = pad_x_cells
        self.mode = (mode or "both").lower()
        self.hwnd = hwnd
        self._cursor_ok = True  # SetCursorPos 失败后改走纯消息点击

    def square_to_screen(self, sq: Square) -> tuple[int, int]:
        col_span = 8.0 + 2.0 * self.pad_x_cells
        row_span = 9.0 + 2.0 * self.pad_y_cells
        cell_w = self.region.width / col_span
        cell_h = self.region.height / row_span
        x = self.region.left + (self.pad_x_cells + sq.file) * cell_w
        y = self.region.top + (self.pad_y_cells + (9 - sq.rank)) * cell_h
        return int(round(x / self.dpi_scale)), int(round(y / self.dpi_scale))

    def _move_cursor(self, x: int, y: int) -> bool:
        """尝试移动光标。成功返回 True。"""
        # 解除可能的光标锁定 / 输入阻塞
        try:
            user32.ClipCursor(None)
            user32.BlockInput(False)
        except Exception:
            pass
        ok = bool(user32.SetCursorPos(int(x), int(y)))
        _send_input_move_abs(x, y)
        # 再用相对移动兜底（部分远程桌面只吃相对）
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        dx, dy = int(x) - int(pt.x), int(y) - int(pt.y)
        if dx or dy:
            user32.mouse_event(MOUSEEVENTF_MOVE, dx, dy, 0, 0)
            user32.SetCursorPos(int(x), int(y))
        time.sleep(0.02)
        user32.GetCursorPos(ctypes.byref(pt))
        if (pt.x, pt.y) != (int(x), int(y)):
            if self._cursor_ok:
                print(
                    f"  !! cursor stuck at ({pt.x},{pt.y}), wanted ({x},{y}), "
                    f"SetCursorPos={ok}. 已切换为窗口消息点击。"
                    " 若仍无效：从开始菜单开 CMD，或右键 play_red_admin.bat 管理员运行"
                    "（勿在 Cursor 内置终端跑点击）。"
                )
            self._cursor_ok = False
            return False
        self._cursor_ok = True
        return True

    def click_xy(self, x: int, y: int) -> None:
        # 光标被系统拦住时（常见于 Cursor 终端 / 完整性级别不一致）改用消息点击
        use_post = self.mode in ("postmessage", "both") or not self._cursor_ok
        use_real = self.mode in ("click", "both", "drag") and self._cursor_ok

        if use_post:
            post_click_screen(x, y, self.hwnd)
        if use_real:
            moved = self._move_cursor(x, y)
            if not moved:
                post_click_screen(x, y, self.hwnd)
                return
            time.sleep(0.03)
            _send_input_click()
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.04)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        elif not use_post:
            # mode=click 且光标已废：仍发消息
            post_click_screen(x, y, self.hwnd)

    def drag_xy(self, x0: int, y0: int, x1: int, y1: int) -> None:
        self._move_cursor(x0, y0)
        time.sleep(0.05)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        _send_input = INPUT()
        _send_input.type = INPUT_MOUSE
        _send_input.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, None)
        user32.SendInput(1, ctypes.byref(_send_input), ctypes.sizeof(INPUT))
        time.sleep(0.08)
        steps = max(8, int(self.move_duration * 60))
        for i in range(1, steps + 1):
            x = int(x0 + (x1 - x0) * i / steps)
            y = int(y0 + (y1 - y0) * i / steps)
            self._move_cursor(x, y)
            time.sleep(self.move_duration / steps)
        time.sleep(0.05)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        up = INPUT()
        up.type = INPUT_MOUSE
        up.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, None)
        user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))

        if self.mode in ("postmessage", "both") and self.hwnd:
            # 消息拖拽：down -> move -> up
            c0x, c0y = _screen_to_client(self.hwnd, x0, y0)
            c1x, c1y = _screen_to_client(self.hwnd, x1, y1)
            user32.SendMessageW(self.hwnd, WM_LBUTTONDOWN, MK_LBUTTON, _lparam(c0x, c0y))
            user32.SendMessageW(self.hwnd, WM_MOUSEMOVE, MK_LBUTTON, _lparam(c1x, c1y))
            user32.SendMessageW(self.hwnd, WM_LBUTTONUP, 0, _lparam(c1x, c1y))

    def click_square(self, sq: Square) -> None:
        x, y = self.square_to_screen(sq)
        print(f"  click {sq.uci} -> screen ({x},{y})")
        self.click_xy(x, y)

    def play_move(self, move: Move) -> None:
        x0, y0 = self.square_to_screen(move.frm)
        x1, y1 = self.square_to_screen(move.to)
        effective = self.mode if self._cursor_ok else "postmessage"
        print(f"  move {move.uci}: ({x0},{y0}) -> ({x1},{y1}) mode={effective}")
        if effective == "drag":
            self.drag_xy(x0, y0, x1, y1)
        elif effective == "both":
            # 先两点点击，再补一枪拖拽，兼容不同棋软
            self.click_xy(x0, y0)
            time.sleep(self.click_interval)
            self.click_xy(x1, y1)
            if self._cursor_ok:
                time.sleep(0.15)
                self.drag_xy(x0, y0, x1, y1)
        else:
            # click / postmessage：两点点击
            self.click_xy(x0, y0)
            time.sleep(self.click_interval)
            self.click_xy(x1, y1)
