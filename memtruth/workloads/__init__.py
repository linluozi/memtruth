"""Registry of calibration workloads.

Each entry names a module whose ``run(scale)`` performs one allocation path.
Modules are imported lazily so that listing workloads never imports numpy or
sqlite3 (which would pollute every measurement's baseline).
"""

from __future__ import annotations

import importlib

WORKLOADS = {
    "small_objects": {
        "module": "memtruth.workloads.small_objects",
        "category": "pymalloc small objects",
        "description": "200k two-key dicts held live",
    },
    "bytes_1k": {
        "module": "memtruth.workloads.bytes_1k",
        "category": "pymalloc >512B blocks",
        "description": "200k 1 KiB bytes objects held live",
    },
    "churn_free": {
        "module": "memtruth.workloads.churn_free",
        "category": "alloc/free churn",
        "description": "200k dicts allocated then freed before measuring",
    },
    "sqlite_rows": {
        "module": "memtruth.workloads.sqlite_rows",
        "category": "C extension (untraced malloc)",
        "description": "in-memory sqlite3 table with 20k rows",
    },
    "numpy_zeros": {
        "module": "memtruth.workloads.numpy_zeros",
        "category": "lazy zero-filled buffer",
        "description": "numpy.zeros(64 MiB) never written to",
    },
    "json_roundtrip": {
        "module": "memtruth.workloads.json_roundtrip",
        "category": "parser (transient buffers)",
        "description": "dump+load of an 8 MiB JSON document",
    },
    "mmap_pages": {
        "module": "memtruth.workloads.mmap_pages",
        "category": "anonymous mmap",
        "description": "32 MiB anonymous mmap, fully written",
    },
    "zlib_zeros": {
        "module": "memtruth.workloads.zlib_zeros",
        "category": "lazy zero-filled buffer",
        "description": "compress 32 MiB of zero bytes",
    },
    "regex_findall": {
        "module": "memtruth.workloads.regex_findall",
        "category": "many small objects from C",
        "description": "re.findall over 1 MiB, 524k result strings",
    },
}


def names() -> list:
    return sorted(WORKLOADS)


def get(name: str) -> dict:
    try:
        return WORKLOADS[name]
    except KeyError:
        raise KeyError(
            "unknown workload %r; known: %s" % (name, ", ".join(names()))
        ) from None


def load(name: str):
    """Import and return the workload module (may import numpy/sqlite3)."""
    return importlib.import_module(get(name)["module"])
