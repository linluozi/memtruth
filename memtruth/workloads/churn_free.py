"""Allocate 200k dicts, drop them all, then measure what the process keeps."""

KEEP = []


def run(scale=1.0):
    n = int(200000 * scale)
    xs = [{"k": i, "v": "x" * 20} for i in range(n)]
    # Touch every element so the list itself cannot be optimised away.
    KEEP.append(len(xs))
    del xs
