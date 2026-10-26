"""从 GitHub Releases / 本地压缩包安装 Pikafish 引擎。"""

from __future__ import annotations

import io
import os
import re
import shutil
import socket
import zipfile
from pathlib import Path

import requests
from tqdm import tqdm

API_LATEST = "https://api.github.com/repos/official-pikafish/Pikafish/releases/latest"

MIRRORS = [
    "https://ghproxy.net/",
    "https://gh-proxy.com/",
    "https://ghfast.top/",
    "",  # 官方兜底
]

EXE_PREFERENCE = [
    "avx2",  # 兼容性最好的高速选项优先
    "bmi2",
    "avxvnni",
    "avx512icl",
    "avx512",
    "sse41-popcnt",
    "ssse3",
    "sse3-popcnt",
    "x86-64",
]

LOCAL_PROXY_CANDIDATES = ("127.0.0.1:7897", "127.0.0.1:7890", "127.0.0.1:10809")


def download_pikafish(out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _maybe_enable_local_proxy()

    print("查询 Pikafish 最新 Release…")
    resp = requests.get(API_LATEST, timeout=60)
    resp.raise_for_status()
    release = resp.json()
    assets = release.get("assets") or []
    asset = _pick_asset(assets)
    if asset is None:
        raise RuntimeError(_manual_hint())

    url = asset["browser_download_url"]
    name = asset["name"]
    print(f"下载: {name}")
    data = _download_with_mirrors(url, name)

    pack_path = out_dir / name
    pack_path.write_bytes(data)
    print(f"压缩包: {pack_path}")
    return install_from_archive(pack_path, out_dir)


def install_from_archive(archive: str | Path, out_dir: str | Path | None = None) -> Path:
    """从本地 .7z / .zip 安装到 engine/。"""
    archive = Path(archive)
    if not archive.exists():
        raise FileNotFoundError(archive)
    out_dir = Path(out_dir) if out_dir else archive.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    extract_dir = out_dir / "_extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir, ignore_errors=True)
    extract_dir.mkdir(parents=True, exist_ok=True)

    print(f"解压: {archive}")
    data = archive.read_bytes()
    lower = archive.name.lower()
    if lower.endswith(".zip"):
        _extract_zip(data, extract_dir)
    elif lower.endswith(".7z"):
        _extract_7z(data, extract_dir)
    else:
        raise RuntimeError(f"不支持的格式: {archive.suffix}（请用 .7z 或 .zip）")

    exe_src = _pick_exe(extract_dir)
    nnue_src = _pick_nnue(extract_dir)
    if exe_src is None:
        raise RuntimeError(f"解压后未找到引擎 exe，内容见: {extract_dir}")

    final_exe = out_dir / "pikafish.exe"
    final_nnue = out_dir / "pikafish.nnue"
    shutil.copy2(exe_src, final_exe)
    print(f"选用引擎: {exe_src.name} -> {final_exe}")
    if nnue_src is not None:
        shutil.copy2(nnue_src, final_nnue)
        print(f"NNUE: {nnue_src.name} -> {final_nnue}")
    else:
        print("警告: 未找到 .nnue")

    shutil.rmtree(extract_dir, ignore_errors=True)
    print(f"完成: {final_exe}")
    return final_exe


def setup_status(root: Path | None = None) -> dict:
    """返回安装进度，便于 CLI 查看。"""
    root = root or Path(__file__).resolve().parent.parent
    engine_dir = root / "engine"
    templates = list((root / "data" / "templates").glob("*.png")) + list(
        (root / "data" / "templates").glob("*.jpg")
    )
    return {
        "engine_exe": (engine_dir / "pikafish.exe").exists(),
        "engine_nnue": (engine_dir / "pikafish.nnue").exists(),
        "calib": (root / "data" / "calib.json").exists(),
        "templates": len(templates),
        "ready_to_play": (
            (engine_dir / "pikafish.exe").exists()
            and (root / "data" / "calib.json").exists()
            and len(templates) >= 7
        ),
    }


def _manual_hint() -> str:
    return (
        "自动下载失败。请手动任选其一：\n"
        "1) https://github.com/official-pikafish/Pikafish/releases/latest\n"
        "2) https://www.pikafish.com/ （百度网盘）\n"
        "下载 .7z 后执行:\n"
        "  python main.py download --from-file <路径\\Pikafish.xxx.7z>"
    )


def _maybe_enable_local_proxy() -> None:
    if os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY"):
        return
    for addr in LOCAL_PROXY_CANDIDATES:
        host, port_s = addr.split(":")
        port = int(port_s)
        if _port_open(host, port):
            proxy = f"http://{addr}"
            os.environ["HTTP_PROXY"] = proxy
            os.environ["HTTPS_PROXY"] = proxy
            os.environ["http_proxy"] = proxy
            os.environ["https_proxy"] = proxy
            print(f"检测到本地代理，已启用: {proxy}")
            return


def _port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _pick_asset(assets: list[dict]) -> dict | None:
    patterns = [
        re.compile(r"pikafish.*\.7z$", re.I),
        re.compile(r"(windows|win).*?\.(zip|7z)$", re.I),
        re.compile(r"\.zip$", re.I),
        re.compile(r"\.7z$", re.I),
    ]
    for pat in patterns:
        for a in assets:
            if pat.search(a.get("name", "")):
                return a
    return assets[0] if assets else None


def _download_with_mirrors(url: str, name: str) -> bytes:
    errors: list[str] = []
    # 已开本地代理时优先官方源
    order = [""] + [m for m in MIRRORS if m] if os.environ.get("HTTP_PROXY") else MIRRORS
    for prefix in order:
        full = f"{prefix}{url}" if prefix else url
        label = prefix or "github.com"
        try:
            print(f"尝试: {label}")
            return _download_bytes(full, name)
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            print(f"失败: {exc}")
    raise RuntimeError("所有下载源均失败:\n" + "\n".join(errors) + "\n" + _manual_hint())


def _download_bytes(url: str, name: str) -> bytes:
    r = requests.get(url, stream=True, timeout=120)
    r.raise_for_status()
    total = int(r.headers.get("content-length", 0))
    buf = io.BytesIO()
    with tqdm(total=total or None, unit="B", unit_scale=True, desc=name) as bar:
        for chunk in r.iter_content(chunk_size=1 << 16):
            if chunk:
                buf.write(chunk)
                bar.update(len(chunk))
    data = buf.getvalue()
    if total and len(data) < total * 0.95:
        raise RuntimeError(f"下载不完整: {len(data)}/{total}")
    if len(data) < 1_000_000:
        raise RuntimeError(f"文件过小，可能不是完整包: {len(data)} bytes")
    return data


def _extract_zip(data: bytes, dest: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(dest)


def _extract_7z(data: bytes, dest: Path) -> None:
    try:
        import py7zr
    except ImportError as exc:
        raise RuntimeError("需要 py7zr：pip install py7zr") from exc
    with py7zr.SevenZipFile(io.BytesIO(data), mode="r") as zf:
        zf.extractall(path=dest)


def _pick_exe(root: Path) -> Path | None:
    exes = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".exe"]
    win_exes = [p for p in exes if "pikafish" in p.name.lower()] or exes
    if not win_exes:
        return None

    def score(p: Path) -> tuple[int, int]:
        name = p.name.lower()
        for i, key in enumerate(EXE_PREFERENCE):
            if key in name:
                return (0, i)
        return (1, 99)

    win_exes.sort(key=score)
    return win_exes[0]


def _pick_nnue(root: Path) -> Path | None:
    nnues = list(root.rglob("*.nnue"))
    if not nnues:
        return None
    for p in nnues:
        if "pikafish" in p.name.lower():
            return p
    return nnues[0]


if __name__ == "__main__":
    download_pikafish(Path(__file__).resolve().parent.parent / "engine")
