#!/usr/bin/env python3
"""Regenerate benchmark/calibration.json and benchmark/raw/*.json.

Usage:
    python3 benchmark/bench.py            # 9 workloads x 3 repeats x 2 modes
    python3 benchmark/bench.py --repeat 5 --scale 1.0
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from memtruth.cli import main as cli_main  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--out", default=str(ROOT / "benchmark" / "calibration.json"))
    ap.add_argument("--raw", default=str(ROOT / "benchmark" / "raw"))
    args = ap.parse_args()
    cmd = ["run", "--repeat", str(args.repeat), "--scale", str(args.scale),
           "--out", args.out, "--raw", args.raw]
    return cli_main(cmd)


if __name__ == "__main__":
    sys.exit(main())
