#!/usr/bin/env python
"""兼容入口：python tools/download_pikafish.py"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from xiangqi_bot.download_pikafish import download_pikafish

if __name__ == "__main__":
    download_pikafish(ROOT / "engine")
