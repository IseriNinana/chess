"""点击自检：依次点帅、炮、将；并打印移动前后真实光标位置。"""

from __future__ import annotations

import time

from xiangqi_bot.board import Square
from xiangqi_bot.control.mouse import MouseController, cursor_pos, enable_dpi_awareness
from xiangqi_bot.vision.calibrate import Calibration
from xiangqi_bot.vision.window import bring_to_front, find_xiangqi_window


def main() -> None:
    enable_dpi_awareness()
    calib = Calibration.load("data/calib.json")
    win = find_xiangqi_window()
    print("window:", None if not win else (win.title, win.hwnd, win.width, win.height))
    if win:
        bring_to_front(win.hwnd)
        time.sleep(0.4)
    mouse = MouseController(
        calib.region,
        pad_x_cells=calib.pad_x_cells,
        pad_y_cells=calib.pad_y_cells,
        mode="click",
        hwnd=win.hwnd if win else None,
    )
    before = cursor_pos()
    print(f"光标现在在: {before}")
    print("3 秒后开始点击：e0(帅附近) -> b2(炮) -> e9(将附近)")
    print("请盯着屏幕上的鼠标箭头看是否跳动。")
    time.sleep(3)
    for sq in (Square(4, 0), Square(1, 2), Square(4, 9)):
        target = mouse.square_to_screen(sq)
        print(f"click {sq.uci} target={target} before={cursor_pos()}")
        mouse.click_square(sq)
        time.sleep(0.15)
        after = cursor_pos()
        dist = abs(after[0] - target[0]) + abs(after[1] - target[1])
        ok = dist < 12
        print(f"  after={after}  {'OK 已移动' if ok else 'FAIL 光标未到目标'}")
        time.sleep(0.85)
    print("完成。")
    if mouse._helper is not None:
        print("本次走独立点击进程。")
    elif not mouse._cursor_ok:
        print("若全程 FAIL：不要从 Cursor 终端启动；用 Win+R 打开 cmd，再运行 test_click.bat")
        print("若象棋是管理员启动的，请用 play_red_admin.bat")


if __name__ == "__main__":
    main()
