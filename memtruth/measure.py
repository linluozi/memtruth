"""Parent side: spawn isolated runs and parse their JSON."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from . import workloads

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class MeasureError(RuntimeError):
    pass


def child_env():
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    parts = [str(PROJECT_ROOT)]
    if existing:
        parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env.pop("PYTHONHASHSEED", None)
    return env


def run_once(workload=None, script=None, mode="traced", scale=1.0, timeout=300,
             python=None):
    """Run one workload in a fresh interpreter and return its record."""
    if (workload is None) == (script is None):
        raise ValueError("pass exactly one of workload= or script=")
    if mode not in ("control", "traced"):
        raise ValueError("mode must be 'control' or 'traced'")
    if workload is not None:
        workloads.get(workload)  # fail fast with the list of known names

    cmd = [python or sys.executable, "-m", "memtruth._worker", "--mode", mode,
           "--scale", repr(scale)]
    if workload is not None:
        cmd += ["--workload", workload]
    else:
        cmd += ["--script", str(script)]

    try:
        proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=child_env(),
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise MeasureError("run timed out after %ss: %s" % (timeout, " ".join(cmd)))

    if proc.returncode != 0:
        raise MeasureError(
            "child exited %s\ncmd: %s\nstderr tail:\n%s"
            % (proc.returncode, " ".join(cmd), proc.stderr[-2000:])
        )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    if not lines:
        raise MeasureError("child produced no output\nstderr:\n%s" % proc.stderr[-2000:])
    try:
        record = json.loads(lines[-1])
    except json.JSONDecodeError:
        raise MeasureError("child output was not JSON: %r" % lines[-1][:500])
    if record.get("error"):
        raise MeasureError(record["error"])
    return record
