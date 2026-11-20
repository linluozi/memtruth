"""Child process that performs exactly one measurement and prints one JSON line.

Every run gets a fresh interpreter so that RSS before the workload is a clean
baseline and one workload cannot leak into the next.
"""

from __future__ import annotations

import argparse
import gc
import importlib
import json
import os
import platform
import runpy
import sys
import tracemalloc

from . import proc, workloads


def _measure(run, mode, scale, label):
    # Take the RSS baseline BEFORE tracing starts: reading /proc allocates
    # strings whose digit widths depend on the process size, so doing it
    # inside the traced window makes traced_peak vary by a few KiB run to run.
    gc.collect()
    before = proc.snapshot()

    tracing = mode == "traced"
    traced_base = 0
    if tracing:
        tracemalloc.start()
        traced_base = tracemalloc.get_traced_memory()[0]

    run()

    # Read the traced numbers before any further /proc reads, so the
    # instrumentation's own allocations are not counted as workload bytes.
    traced_cur = traced_peak = traced_final = None
    if tracing:
        cur, peak_bytes = tracemalloc.get_traced_memory()
        traced_cur = cur - traced_base
        traced_peak = peak_bytes - traced_base

    peak = proc.snapshot()
    gc.collect()
    final = proc.snapshot()
    if tracing:
        traced_final = tracemalloc.get_traced_memory()[0] - traced_base
        tracemalloc.stop()

    return {
        "workload": label,
        "mode": mode,
        "scale": scale,
        "rss_before": before["rss"],
        "rss_peak_delta": max(0, peak["hwm"] - before["rss"]),
        "rss_final_delta": final["rss"] - before["rss"],
        "traced_cur": traced_cur,
        "traced_peak": traced_peak,
        "traced_final": traced_final,
        "gc_collections": sum(stat["collections"] for stat in gc.get_stats()),
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="one isolated memtruth measurement")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--workload")
    src.add_argument("--script")
    ap.add_argument("--mode", choices=("control", "traced"), required=True)
    ap.add_argument("--scale", type=float, default=1.0)
    args = ap.parse_args(argv)

    if args.workload:
        workloads.get(args.workload)  # validate before importing anything heavy
        module = workloads.load(args.workload)
        label = args.workload
        run = lambda: module.run(args.scale)
    else:
        path = os.path.abspath(args.script)
        if not os.path.isfile(path):
            print(json.dumps({"error": "no such script: %s" % path}))
            return 2
        label = os.path.basename(path)
        run = lambda: runpy.run_path(path, run_name="__main__")

    record = _measure(run, args.mode, args.scale, label)
    print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
