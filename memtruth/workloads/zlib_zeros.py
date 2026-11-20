"""Compress 32 MiB of zero bytes: the input buffer is traced but never resident."""

import zlib

KEEP = []


def run(scale=1.0):
    size = int(32 * 1024 * 1024 * scale)
    buf = bytes(size)  # calloc: zero pages are shared until written
    KEEP.append(zlib.compress(buf, 1))
    KEEP.append(buf)
