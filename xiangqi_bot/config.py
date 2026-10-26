"""配置加载。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else project_root() / "config.yaml"
    with cfg_path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    root = project_root()

    def _abs(p: str | Path) -> str:
        path_obj = Path(p)
        if not path_obj.is_absolute():
            path_obj = root / path_obj
        return str(path_obj)

    if "engine" in cfg:
        if cfg["engine"].get("path"):
            cfg["engine"]["path"] = _abs(cfg["engine"]["path"])
        if cfg["engine"].get("nnue"):
            cfg["engine"]["nnue"] = _abs(cfg["engine"]["nnue"])
    if "vision" in cfg:
        for key in ("calib_file", "templates_dir", "cls_dataset", "cnn_model"):
            if cfg["vision"].get(key):
                cfg["vision"][key] = _abs(cfg["vision"][key])
    if "bot" in cfg and cfg["bot"].get("debug_dir"):
        cfg["bot"]["debug_dir"] = _abs(cfg["bot"]["debug_dir"])
    return cfg
