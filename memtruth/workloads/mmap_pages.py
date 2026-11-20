"""32 MiB anonymous mmap, fully written: mapping is invisible to tracemalloc."""

import mmap

KEEP = []


def run(scale=1.0):
    size = int(32 * 1024 * 1024 * scale)
    m = mmap.mmap(-1, size)
    m.write(b"x" * size)
    KEEP.append(m)
