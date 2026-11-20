"""Process resident-memory readings from /proc (Linux only).

``tracemalloc`` reports bytes requested from Python's allocators.  The kernel
reports pages actually resident in RAM.  These are different quantities; this
module is the page-side half of the comparison.
"""

from __future__ import annotations

STATUS_PATH = "/proc/self/status"


def parse_status(text: str) -> dict:
    """Parse the ``kB`` fields of /proc/<pid>/status into bytes.

    Only the keys this package needs are returned.  Values are ints in bytes;
    unknown or malformed lines are ignored rather than guessed at.
    """
    wanted = {"VmRSS", "VmHWM", "VmSize"}
    out = {}
    for line in text.splitlines():
        key, sep, rest = line.partition(":")
        if not sep or key not in wanted:
            continue
        parts = rest.split()
        if len(parts) >= 2 and parts[1].lower() == "kb":
            out[key] = int(parts[0]) * 1024
    return out


def read_status(path: str = STATUS_PATH) -> dict:
    with open(path, "r", encoding="ascii", errors="replace") as fh:
        return parse_status(fh.read())


def snapshot(path: str = STATUS_PATH) -> dict:
    """Return ``{"rss": bytes, "hwm": bytes}`` for the current process.

    ``hwm`` is the high-water mark since process start, so it is the closest
    thing /proc offers to a peak-RSS measurement.  Raises if /proc is not
    readable: silently returning zeros would turn a missing instrument into a
    fake result.
    """
    stats = read_status(path)
    if "VmRSS" not in stats:
        raise RuntimeError(
            "cannot read VmRSS from %s; memtruth requires Linux /proc" % path
        )
    return {"rss": stats["VmRSS"], "hwm": stats.get("VmHWM", stats["VmRSS"])}
