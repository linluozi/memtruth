"""Real code: compile every .py file of a few CPython stdlib packages.

Unlike the synthetic workloads this reads a few hundred real source files and
keeps the resulting code objects, so the allocation mix is not hand-picked.
"""

import glob
import os
import sys

KEEP = []

_PACKAGES = ("json", "email", "http", "unittest", "asyncio")


def _sources():
    root = os.path.dirname(os.__file__)
    files = []
    for pkg in _PACKAGES:
        files.extend(sorted(glob.glob(os.path.join(root, pkg, "**", "*.py"),
                                      recursive=True)))
    return files[::3]  # every third file keeps the workload around 5 s


def run(scale=1.0):
    files = _sources()
    if scale < 1.0:
        files = files[:max(1, int(len(files) * scale))]
    codes = []
    for path in files:
        try:
            with open(path, "rb") as fh:
                codes.append(compile(fh.read(), path, "exec"))
        except (SyntaxError, UnicodeDecodeError):
            continue
    KEEP.append(codes)
    KEEP.append(len(codes))
