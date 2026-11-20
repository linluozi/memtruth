"""Command line interface: list, run, audit, report."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

from . import measure, report, verdict, workloads

DEFAULT_OUT = Path("benchmark/calibration.json")
DEFAULT_RAW = Path("benchmark/raw")


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def _collect(targets, repeats, scale, raw_dir, script=None):
    runs, skipped = [], []
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    for name in targets:
        for i in range(repeats):
            for mode in ("control", "traced"):
                try:
                    rec = measure.run_once(workload=None if script else name,
                                           script=script, mode=mode, scale=scale)
                except measure.MeasureError as exc:
                    if "ModuleNotFoundError" in str(exc):
                        skipped.append({"workload": name, "reason": "optional dependency missing"})
                        break
                    raise
                runs.append(rec)
                _write_json(raw_dir / ("%s-%s-%d.json" % (name, mode, i)), rec)
        else:
            continue
        continue
    return runs, skipped


def cmd_list(args):
    for name in workloads.names():
        meta = workloads.get(name)
        print("%-16s %-32s %s" % (name, meta["category"], meta["description"]))
    return 0


def cmd_run(args):
    targets = args.workloads or workloads.names()
    for name in targets:
        workloads.get(name)
    started = time.time()
    runs, skipped = _collect(targets, args.repeat, args.scale, args.raw)
    if not runs:
        print("no measurements produced", file=sys.stderr)
        return 2
    summary = report.summarize(runs)
    table = report.rows(summary)
    payload = {
        "tool": "memtruth",
        "version": "0.1.0",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "scale": args.scale,
        "repeats": args.repeat,
        "elapsed_seconds": round(time.time() - started, 3),
        "runs": runs,
        "summary": summary,
        "table": table,
        "skipped": skipped,
    }
    if args.out:
        _write_json(args.out, payload)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(report.to_markdown(table))
        for row in table:
            w = row["verdict"].get("warning")
            if w:
                print("  note: %s: %s" % (row["workload"], w))
        if skipped:
            print("  skipped: %s" % ", ".join(s["workload"] for s in skipped))
    return 0


def cmd_audit(args):
    script = Path(args.script)
    if not script.is_file():
        print("no such script: %s" % script, file=sys.stderr)
        return 2
    runs, _ = _collect([script.name], args.repeat, 1.0, args.raw, script=script)
    summary = report.summarize(runs)
    table = report.rows(summary)
    if args.json:
        print(json.dumps({"table": table, "runs": runs}, indent=2, sort_keys=True))
    else:
        print("script: %s" % script)
        print(report.to_markdown(table))
    return 0


def evaluate_gate(table, max_instrument_ratio=1.25, strict=False):
    """Return (violations, lines). Pure function so it is testable offline."""
    violations, lines = [], []
    for row in table:
        name = row["workload"]
        v = row["verdict"]
        reasons = []
        ratio = v.get("rss_traced_to_control")
        rss_control = row.get("rss_control") or 0
        if rss_control < verdict.NOISE_FLOOR:
            ratio = None  # both sides are inside the noise floor
        if ratio is not None and ratio > max_instrument_ratio:
            reasons.append("profiler inflates peak RSS x%.2f > x%.2f"
                           % (ratio, max_instrument_ratio))
        if strict and v["agreement"] != "agree":
            reasons.append("verdict is %s, not agree" % v["agreement"])
        if reasons:
            violations.append({"workload": name, "reasons": reasons})
            lines.append("FAIL %-16s %s" % (name, "; ".join(reasons)))
        else:
            lines.append("PASS %-16s traced/RSS=%s agreement=%s"
                         % (name,
                            "n/a" if v.get("traced_to_rss") is None else "%.2fx" % v["traced_to_rss"],
                            v["agreement"]))
    return violations, lines


def cmd_gate(args):
    payload = json.loads(Path(args.path).read_text(encoding="utf-8"))
    table = payload.get("table") or report.rows(payload["summary"])
    if args.allow:
        table = [r for r in table if r["workload"] not in set(args.allow)]
    violations, lines = evaluate_gate(table, args.max_instrument_ratio, args.strict)
    for line in lines:
        print(line)
    if violations:
        print("%d workload(s) failed the memory-instrument gate" % len(violations),
              file=sys.stderr)
        return 1
    print("gate passed: %d workload(s) within x%.2f instrument cost%s"
          % (len(table), args.max_instrument_ratio,
             ", all verdicts agree" if args.strict else ""))
    return 0


def cmd_report(args):
    payload = json.loads(Path(args.path).read_text(encoding="utf-8"))
    table = payload.get("table") or report.rows(payload["summary"])
    if args.json:
        print(json.dumps(table, indent=2, sort_keys=True))
    else:
        print(report.to_markdown(table))
    return 0


def build_parser():
    ap = argparse.ArgumentParser(
        prog="memtruth",
        description="Compare tracemalloc bytes with real resident memory, and "
                    "measure what the profiler itself costs.")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="list calibration workloads")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("run", help="measure workloads in isolated processes")
    p.add_argument("workloads", nargs="*", help="workload names (default: all)")
    p.add_argument("--repeat", type=int, default=3)
    p.add_argument("--scale", type=float, default=1.0)
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--raw", default=str(DEFAULT_RAW))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("audit", help="measure an arbitrary script in both modes")
    p.add_argument("script")
    p.add_argument("--repeat", type=int, default=2)
    p.add_argument("--raw", default=str(DEFAULT_RAW))
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("gate", help="fail CI when the profiler distorts the harness")
    p.add_argument("path", help="calibration JSON produced by 'run'")
    p.add_argument("--max-instrument-ratio", type=float, default=1.25,
                   help="fail if peak RSS with tracing exceeds this multiple of the untraced peak")
    p.add_argument("--strict", action="store_true",
                   help="also fail when a verdict is not 'agree'")
    p.add_argument("--allow", nargs="*", default=[], help="workloads to ignore")
    p.set_defaults(func=cmd_gate)

    p = sub.add_parser("report", help="render a saved calibration JSON")
    p.add_argument("path")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_report)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    if getattr(args, "repeat", 1) < 1:
        print("--repeat must be >= 1", file=sys.stderr)
        return 2
    return args.func(args)
