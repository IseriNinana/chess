"""Windows 窗口查找（天天象棋等）。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

user32 = ctypes.windll.user32

DEFAULT_TITLE_KEYWORDS = ("天天象棋", "中国象棋", "象棋", "QQ象棋", "雷电模拟器")


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    def as_region_dict(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }


def list_windows(keywords: tuple[str, ...] | None = None) -> list[WindowInfo]:
    """枚举可见顶层窗口；keywords 为空则返回全部有标题窗口。"""
    keywords = keywords if keywords is not None else DEFAULT_TITLE_KEYWORDS
    results: list[WindowInfo] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd, _lparam):  # noqa: ANN001
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if not title:
            return True
        if keywords and not any(k.lower() in title.lower() for k in keywords):
            return True
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        info = WindowInfo(int(hwnd), title, rect.left, rect.top, rect.right, rect.bottom)
        if info.width < 200 or info.height < 200:
            return True
        results.append(info)
        return True

    user32.EnumWindows(_enum, 0)
    results.sort(key=lambda w: (-w.width * w.height, w.title))
    return results


def find_xiangqi_window() -> WindowInfo | None:
    wins = list_windows(DEFAULT_TITLE_KEYWORDS)
    return wins[0] if wins else None


def bring_to_front(hwnd: int) -> None:
    SW_RESTORE = 9
    user32.ShowWindow(hwnd, SW_RESTORE)
    # AllowSetForegroundWindow + AttachThreadInput 提高置前成功率
    try:
        user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
    except Exception:
        pass
    fg = user32.GetForegroundWindow()
    if fg and fg != hwnd:
        pid = wintypes.DWORD()
        tid_fg = user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
        tid_tg = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if tid_fg and tid_tg and tid_fg != tid_tg:
            user32.AttachThreadInput(tid_fg, tid_tg, True)
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
            user32.AttachThreadInput(tid_fg, tid_tg, False)
            return
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
