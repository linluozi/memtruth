"""200k two-key dicts held live: the pymalloc small-object path."""

KEEP = []


def run(scale=1.0):
    n = int(200000 * scale)
    KEEP.append([{"k": i, "v": "x" * 20} for i in range(n)])
