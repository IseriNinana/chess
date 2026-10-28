"""鼠标控制：真实 SendInput，以及 Cursor 终端拦注入时的独立点击进程。"""

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
MOUSEEVENTF_VIRTUALDESK = 0x4000
INPUT_MOUSE = 0

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200
MK_LBUTTON = 0x0001

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]

    _anonymous_ = ("i",)
    _fields_ = [("type", wintypes.DWORD), ("i", _I)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT


def enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


enable_dpi_awareness()


def _virtual_desk() -> tuple[int, int, int, int]:
    SM_XVIRTUALSCREEN = 76
    SM_YVIRTUALSCREEN = 77
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79
    return (
        int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN)),
        int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN)),
        int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)),
        int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)),
    )


def _abs_norm(x: int, y: int) -> tuple[int, int]:
    vx, vy, vw, vh = _virtual_desk()
    ax = int(round((int(x) - vx) * 65535 / max(vw - 1, 1)))
    ay = int(round((int(y) - vy) * 65535 / max(vh - 1, 1)))
    return max(0, min(65535, ax)), max(0, min(65535, ay))


def _mi(dx: int, dy: int, flags: int) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi = MOUSEINPUT(dx, dy, 0, flags, 0, 0)
    return inp


def send_input(events: list[INPUT]) -> int:
    if not events:
        return 0
    arr = (INPUT * len(events))(*events)
    return int(user32.SendInput(len(events), arr, ctypes.sizeof(INPUT)))


def cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def send_move_abs(x: int, y: int) -> int:
    ax, ay = _abs_norm(x, y)
    flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    n = send_input([_mi(ax, ay, flags)])
    if n != 1:
        user32.SetCursorPos(int(x), int(y))
    return n


def send_click_at(x: int, y: int) -> bool:
    """在屏幕坐标点击。按下与抬起分开发送，避免游戏把瞬时 down-up 丢掉。"""
    try:
        user32.ClipCursor(None)
        user32.BlockInput(False)
    except Exception:
        pass
    ax, ay = _abs_norm(x, y)
    move = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    send_input([_mi(ax, ay, move)])
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.04)
    down_n = send_input([_mi(0, 0, MOUSEEVENTF_LEFTDOWN)])
    if not down_n:
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.06)
    up_n = send_input([_mi(0, 0, MOUSEEVENTF_LEFTUP)])
    if not up_n:
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    return bool(down_n or up_n)


def send_drag_at(x0: int, y0: int, x1: int, y1: int, duration: float = 0.12) -> None:
    send_move_abs(x0, y0)
    user32.SetCursorPos(int(x0), int(y0))
    time.sleep(0.05)
    send_input([_mi(0, 0, MOUSEEVENTF_LEFTDOWN)])
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.08)
    steps = max(8, int(duration * 60))
    for i in range(1, steps + 1):
        x = int(x0 + (x1 - x0) * i / steps)
        y = int(y0 + (y1 - y0) * i / steps)
        send_move_abs(x, y)
        user32.SetCursorPos(x, y)
        time.sleep(duration / steps)
    time.sleep(0.05)
    send_input([_mi(0, 0, MOUSEEVENTF_LEFTUP)])
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def injection_works() -> bool:
    """试着把光标挪 1 像素再还原。失败说明本进程鼠标被拦（常见于 Cursor 终端）。"""
    x, y = cursor_pos()
    tx, ty = x + 1, y
    try:
        user32.ClipCursor(None)
        user32.BlockInput(False)
    except Exception:
        pass
    user32.SetCursorPos(tx, ty)
    send_move_abs(tx, ty)
    time.sleep(0.03)
    nx, ny = cursor_pos()
    user32.SetCursorPos(x, y)
    send_move_abs(x, y)
    return abs(nx - tx) <= 2 and abs(ny - ty) <= 2


def _lparam(x: int, y: int) -> int:
    return (int(y) << 16) | (int(x) & 0xFFFF)


def _screen_to_client(hwnd: int, x: int, y: int) -> tuple[int, int]:
    pt = wintypes.POINT(x, y)
    user32.ScreenToClient(hwnd, ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def _window_from_point(x: int, y: int) -> int:
    return int(user32.WindowFromPoint(wintypes.POINT(int(x), int(y))))


def post_click_screen(x: int, y: int, hwnd: int | None = None) -> None:
    """向命中控件发客户区点击。始终优先 WindowFromPoint，避免点到外壳窗口。"""
    hit = _window_from_point(x, y)
    targets: list[int] = []
    for cand in (hit, hwnd or 0):
        if cand and cand not in targets:
            targets.append(int(cand))
    if not targets:
        return
    for target in targets:
        cx, cy = _screen_to_client(target, x, y)
        if cx < -50 or cy < -50:
            continue
        user32.SendMessageW(target, WM_MOUSEMOVE, 0, _lparam(cx, cy))
        user32.SendMessageW(target, WM_LBUTTONDOWN, MK_LBUTTON, _lparam(cx, cy))
        time.sleep(0.04)
        user32.SendMessageW(target, WM_LBUTTONUP, 0, _lparam(cx, cy))
        root = int(user32.GetAncestor(target, 2)) if target else 0
        if root and root not in targets:
            cx2, cy2 = _screen_to_client(root, x, y)
            user32.SendMessageW(root, WM_LBUTTONDOWN, MK_LBUTTON, _lparam(cx2, cy2))
            time.sleep(0.02)
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
        mode: str = "click",  # click | drag | postmessage | both
        hwnd: int | None = None,
    ):
        self.region = board_region
        self.dpi_scale = dpi_scale or 1.0
        self.move_duration = move_duration
        self.click_interval = click_interval
        self.pad_y_cells = pad_y_cells
        self.pad_x_cells = pad_x_cells
        self.mode = (mode or "click").lower()
        self.hwnd = hwnd
        self._cursor_ok = True
        self._helper = None
        self._probe_injection()

    def _probe_injection(self) -> None:
        ok = injection_works()
        self._cursor_ok = ok
        if ok:
            print("鼠标注入: 本进程可用", flush=True)
            return
        print(
            "鼠标注入: 本进程被拦截（Cursor 终端 / 完整性级别）。"
            "正在启动独立点击进程…",
            flush=True,
        )
        try:
            from .click_agent import ClickAgentClient

            self._helper = ClickAgentClient()
            if self._helper.ensure():
                print("鼠标注入: 独立点击进程已就绪", flush=True)
            else:
                self._helper = None
                print(
                    "鼠标注入: 独立进程启动失败。"
                    "请从开始菜单开 CMD，或右键 play_red_admin.bat 管理员运行。",
                    flush=True,
                )
        except Exception as exc:
            self._helper = None
            print(f"鼠标注入: 独立进程异常 {exc}", flush=True)

    def square_to_screen(self, sq: Square) -> tuple[int, int]:
        col_span = 8.0 + 2.0 * self.pad_x_cells
        row_span = 9.0 + 2.0 * self.pad_y_cells
        cell_w = self.region.width / col_span
        cell_h = self.region.height / row_span
        x = self.region.left + (self.pad_x_cells + sq.file) * cell_w
        y = self.region.top + (self.pad_y_cells + (9 - sq.rank)) * cell_h
        return int(round(x / self.dpi_scale)), int(round(y / self.dpi_scale))

    def _real_click(self, x: int, y: int) -> bool:
        if self._helper is not None:
            if self._helper.click(x, y):
                return True
        ok = send_click_at(x, y)
        after = cursor_pos()
        if abs(after[0] - int(x)) > 8 or abs(after[1] - int(y)) > 8:
            self._cursor_ok = False
            if self._helper is None:
                try:
                    from .click_agent import ClickAgentClient

                    self._helper = ClickAgentClient()
                    if self._helper.ensure():
                        return self._helper.click(x, y)
                except Exception:
                    pass
            return False
        self._cursor_ok = True
        return ok or True

    def _real_drag(self, x0: int, y0: int, x1: int, y1: int) -> None:
        if self._helper is not None:
            if self._helper.drag(x0, y0, x1, y1, self.move_duration):
                return
        send_drag_at(x0, y0, x1, y1, self.move_duration)

    def click_xy(self, x: int, y: int) -> None:
        if self.mode == "postmessage":
            post_click_screen(x, y, self.hwnd)
            return
        self._real_click(x, y)

    def drag_xy(self, x0: int, y0: int, x1: int, y1: int) -> None:
        self._real_drag(x0, y0, x1, y1)

    def click_square(self, sq: Square) -> None:
        x, y = self.square_to_screen(sq)
        print(f"  click {sq.uci} -> screen ({x},{y})")
        self.click_xy(x, y)

    def play_move(self, move: Move) -> None:
        x0, y0 = self.square_to_screen(move.frm)
        x1, y1 = self.square_to_screen(move.to)
        via = "helper" if self._helper is not None else ("inproc" if self._cursor_ok else "postmessage")
        print(f"  move {move.uci}: ({x0},{y0}) -> ({x1},{y1}) mode={self.mode} via={via}")
        if self.mode == "drag":
            self.drag_xy(x0, y0, x1, y1)
            return
        self.click_xy(x0, y0)
        time.sleep(self.click_interval)
        self.click_xy(x1, y1)
