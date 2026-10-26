#!/usr/bin/env python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from xiangqi_bot.__main__ import main

if __name__ == "__main__":
    main(["calibrate", *sys.argv[1:]])
