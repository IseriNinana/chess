"""命令行入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config, project_root


def cmd_calibrate(args: argparse.Namespace) -> None:
    from .vision.calibrate import interactive_calibrate

    cfg = load_config(args.config)
    path = args.output or cfg["vision"]["calib_file"]
    interactive_calibrate(cfg["screen"].get("monitor", 1), path)


def cmd_templates(args: argparse.Namespace) -> None:
    from .tools_capture_templates import run_capture_templates

    cfg = load_config(args.config)
    run_capture_templates(cfg, force=args.force)


def cmd_preview(args: argparse.Namespace) -> None:
    import cv2

    from .vision.calibrate import Calibration
    from .vision.capture import ScreenCapture
    from .vision.detect import annotate_board
    from .vision.factory import make_detector

    cfg = load_config(args.config)
    if args.backend:
        cfg.setdefault("vision", {})["backend"] = args.backend
    calib = Calibration.load(cfg["vision"]["calib_file"])
    det = make_detector(cfg["vision"])
    if not det.ready:
        raise SystemExit("识别器未就绪（检查 templates 或 cnn 模型）")
    with ScreenCapture(cfg["screen"].get("monitor", 1)) as cap:
        while True:
            img = cap.grab_region(calib.region)
            board, guesses = det.detect_board(img, calib)
            vis = annotate_board(img, calib, board, guesses)
            cv2.imshow("识别预览 - Q退出", vis)
            print(board.to_fen(), end="\r")
            if cv2.waitKey(100) & 0xFF in (ord("q"), ord("Q"), 27):
                break
    cv2.destroyAllWindows()
    print()
    print(board.pretty())


def cmd_analyse(args: argparse.Namespace) -> None:
    from .engine import PikafishEngine
    from .vision.calibrate import Calibration
    from .vision.capture import ScreenCapture
    from .vision.factory import make_detector

    cfg = load_config(args.config)
    if args.backend:
        cfg.setdefault("vision", {})["backend"] = args.backend
    calib = Calibration.load(cfg["vision"]["calib_file"])
    det = make_detector(cfg["vision"])
    if not det.ready:
        raise SystemExit("识别器未就绪（检查 templates 或 cnn 模型）")
    with ScreenCapture(cfg["screen"].get("monitor", 1)) as cap:
        img = cap.grab_region(calib.region)
    board, _ = det.detect_board(img, calib)
    board = board.normalize_red_bottom()
    board.side_to_move = "w" if args.side == "red" else "b"
    print(board.pretty())
    eng = cfg["engine"]
    with PikafishEngine(eng["path"], eng.get("nnue"), int(eng.get("threads", 4)), int(eng.get("hash_mb", 128))) as engine:
        result = engine.analyse(board, movetime_ms=int(args.movetime))
    print(f"最佳着法: {result['move'].uci}  评分(cp): {result['score_cp']}")


def cmd_collect_cls(args: argparse.Namespace) -> None:
    from .tools_collect_cls import run_collect_cls

    cfg = load_config(args.config)
    run_collect_cls(
        cfg,
        fen=args.fen,
        assume_start=args.assume_start,
        from_image=args.from_image,
        bootstrap_templates=args.bootstrap_templates,
        shots=args.shots,
        delay=args.delay,
    )


def cmd_train_cls(args: argparse.Namespace) -> None:
    from .train_cls import run_train_cls

    cfg = load_config(args.config)
    run_train_cls(cfg, epochs=args.epochs, batch_size=args.batch_size, lr=args.lr)


def cmd_play(args: argparse.Namespace) -> None:
    from .bot import XiangqiBot

    cfg = load_config(args.config)
    if args.side:
        cfg.setdefault("bot", {})["side"] = args.side
    if args.movetime:
        cfg.setdefault("engine", {})["movetime_ms"] = args.movetime
    bot = XiangqiBot(cfg)
    try:
        bot.run()
    except KeyboardInterrupt:
        print("\n中断")
        bot.close()


def cmd_download(args: argparse.Namespace) -> None:
    from .download_pikafish import download_pikafish, install_from_archive

    out = Path(args.output) if args.output else project_root() / "engine"
    if args.from_file:
        install_from_archive(args.from_file, out)
    else:
        download_pikafish(out)


def cmd_status(args: argparse.Namespace) -> None:
    from pathlib import Path

    from .download_pikafish import setup_status
    from .vision.factory import detector_status

    st = setup_status(project_root())
    cfg = load_config(args.config)
    vis = cfg.get("vision", {})
    cnn_path = Path(vis.get("cnn_model") or "data/models/piece_cls.onnx")
    print("安装进度:")
    print(f"  Pikafish 引擎 : {'OK' if st['engine_exe'] else '缺少 engine/pikafish.exe'}")
    print(f"  NNUE 网络     : {'OK' if st['engine_nnue'] else '缺少 engine/pikafish.nnue'}")
    print(f"  棋盘校准      : {'OK' if st['calib'] else '未做 (python main.py calibrate)'}")
    print(f"  棋子模板      : {st['templates']} 个 (建议 >= 14)")
    print(f"  识别后端      : {detector_status(vis)}")
    print(f"  CNN 模型      : {'OK' if cnn_path.exists() else '缺少 (collect-cls + train-cls)'}")
    print(f"  可自动下棋    : {'是' if st['ready_to_play'] else '否'}")
    if not st["engine_exe"]:
        print("\n建议: 打开 https://www.pikafish.com/ 用百度网盘下载，然后:")
        print("  python main.py download --from-file <你的7z路径>")
    if str(vis.get("backend", "")).lower() == "cnn" and not cnn_path.exists():
        print("\nCNN 流程:")
        print("  python main.py collect-cls --bootstrap-templates")
        print("  python main.py collect-cls --assume-start --shots 3")
        print("  python main.py train-cls")


def cmd_setup(args: argparse.Namespace) -> None:
    from .setup_wizard import run_setup

    run_setup(args.config, wait_seconds=args.wait)


def cmd_windows(args: argparse.Namespace) -> None:
    from .vision.window import list_windows

    wins = list_windows(None if args.all else ("天天象棋", "象棋", "棋"))
    if not wins:
        print("未找到匹配窗口。请先打开天天象棋。")
        return
    for w in wins:
        print(f"[{w.hwnd}] {w.title}  {w.width}x{w.height} @({w.left},{w.top})")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="xiangqi_bot",
        description="天天象棋自动下棋 (Python + OpenCV + Pikafish)",
    )
    p.add_argument("-c", "--config", default=None, help="配置文件路径")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("status", help="查看安装/校准进度")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("setup", help="引导完成引擎/校准/模板")
    s.add_argument("--wait", type=int, default=300, help="等待游戏窗口秒数")
    s.set_defaults(func=cmd_setup)

    s = sub.add_parser("windows", help="列出可能的象棋窗口")
    s.add_argument("--all", action="store_true", help="列出全部可见窗口")
    s.set_defaults(func=cmd_windows)

    s = sub.add_parser("download", help="下载 Pikafish 引擎")
    s.add_argument("-o", "--output", default=None)
    s.add_argument("--from-file", default=None, help="从本地 .7z/.zip 安装")
    s.set_defaults(func=cmd_download)

    s = sub.add_parser("calibrate", help="框选棋盘区域并保存校准")
    s.add_argument("-o", "--output", default=None)
    s.set_defaults(func=cmd_calibrate)

    s = sub.add_parser("templates", help="交互采集棋子模板")
    s.add_argument("--force", action="store_true", help="覆盖已有模板")
    s.set_defaults(func=cmd_templates)

    s = sub.add_parser("preview", help="实时预览识别结果")
    s.add_argument("--backend", choices=["template", "cnn"], default=None)
    s.set_defaults(func=cmd_preview)

    s = sub.add_parser("analyse", help="识别当前局面并用引擎分析")
    s.add_argument("--side", choices=["red", "black"], default="red")
    s.add_argument("--movetime", type=int, default=1000)
    s.add_argument("--backend", choices=["template", "cnn"], default=None)
    s.set_defaults(func=cmd_analyse)

    s = sub.add_parser("collect-cls", help="采集 CNN 分类数据集")
    s.add_argument("--assume-start", action="store_true", help="按标准开局 FEN 打标截屏")
    s.add_argument("--fen", default=None, help="自定义 FEN 打标")
    s.add_argument("--from-image", default=None, help="从本地棋盘截图切格（需 FEN）")
    s.add_argument("--bootstrap-templates", action="store_true", help="从旧模板增强冷启动样本")
    s.add_argument("--shots", type=int, default=1, help="截屏次数")
    s.add_argument("--delay", type=float, default=0.4, help="多次截屏间隔秒")
    s.set_defaults(func=cmd_collect_cls)

    s = sub.add_parser("train-cls", help="训练棋子 CNN 并导出 ONNX")
    s.add_argument("--epochs", type=int, default=40)
    s.add_argument("--batch-size", type=int, default=64)
    s.add_argument("--lr", type=float, default=1e-3)
    s.set_defaults(func=cmd_train_cls)

    s = sub.add_parser("play", help="自动下棋")
    s.add_argument("--side", choices=["auto", "red", "black"], default=None)
    s.add_argument("--movetime", type=int, default=None)
    s.set_defaults(func=cmd_play)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
