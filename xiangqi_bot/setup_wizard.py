"""引导完成引擎 / 校准 / 模板采集。"""

from __future__ import annotations

import time
from pathlib import Path

from .config import load_config, project_root
from .download_pikafish import setup_status


def run_setup(config_path: str | None = None, wait_seconds: int = 300) -> None:
    cfg = load_config(config_path)
    root = project_root()
    st = setup_status(root)
    print("=== 天天象棋 Bot 引导安装 ===\n")

    # 1. 引擎
    if not st["engine_exe"]:
        print("[1/4] 缺少 Pikafish，开始下载…")
        from .download_pikafish import download_pikafish

        download_pikafish(root / "engine")
    else:
        print("[1/4] 引擎 OK")

    # 2. 等待游戏窗口
    print("\n[2/4] 请打开《天天象棋》，进入一盘可见完整棋盘的对局/残局。")
    print(f"等待窗口中（最多 {wait_seconds}s）…")
    win = _wait_game_window(wait_seconds)
    if win is None:
        print("未检测到象棋窗口。可稍后手动：")
        print("  python main.py calibrate")
        print("  python main.py templates")
        return
    print(f"已找到窗口: {win.title}  ({win.width}x{win.height})")
    try:
        from .vision.window import bring_to_front

        bring_to_front(win.hwnd)
    except Exception:
        pass
    time.sleep(0.5)

    # 3. 校准
    calib_file = Path(cfg["vision"]["calib_file"])
    if calib_file.exists():
        ans = input("\n[3/4] 已有校准文件，是否重新校准？[y/N] ").strip().lower()
        need_cal = ans in ("y", "yes")
    else:
        need_cal = True
        print("\n[3/4] 开始校准：拖拽框选棋盘最外圈交叉点外接矩形，Enter 确认。")
        input("准备好后按 Enter 继续…")
    if need_cal:
        from .vision.calibrate import interactive_calibrate

        interactive_calibrate(cfg["screen"].get("monitor", 1), calib_file)
    else:
        print("[3/4] 跳过校准")

    # 4. 模板
    templates_dir = Path(cfg["vision"]["templates_dir"])
    n = len(list(templates_dir.glob("*.png")) + list(templates_dir.glob("*.jpg")))
    if n >= 14:
        ans = input(f"\n[4/4] 已有 {n} 个模板，是否重新采集？[y/N] ").strip().lower()
        need_tpl = ans in ("y", "yes")
    else:
        need_tpl = True
        print(f"\n[4/4] 当前模板 {n} 个，开始采集 14 种棋子。")
        print("提示：开局局面最方便；依次点击每种棋子中心后按 Enter。")
        input("准备好后按 Enter 继续…")
    if need_tpl:
        from .tools_capture_templates import run_capture_templates

        run_capture_templates(cfg, force=True)

    st = setup_status(root)
    print("\n=== 完成 ===")
    print(f"引擎={st['engine_exe']} 校准={st['calib']} 模板={st['templates']}")
    if st["ready_to_play"]:
        print("可以开自动下棋了：")
        print("  python main.py preview   # 先确认识别")
        print("  python main.py play")
    else:
        print("尚未就绪，请检查 status / 重新校准与采模板。")


def _wait_game_window(timeout: int):
    from .vision.window import find_xiangqi_window, list_windows

    deadline = time.time() + timeout
    while time.time() < deadline:
        win = find_xiangqi_window()
        if win:
            return win
        # 偶尔打印当前相关窗口，方便用户对照
        wins = list_windows(("棋", "chess", "Chess"))
        if wins:
            print("  看到的相关窗口:", ", ".join(w.title for w in wins[:5]))
        time.sleep(2)
    return None
