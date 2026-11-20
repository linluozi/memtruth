"""numpy.zeros(64 MiB) that is never written to: virtual, mostly not resident."""

import numpy as np

KEEP = []


def run(scale=1.0):
    n = int(64 * 1024 * 1024 * scale // 8)
    KEEP.append(np.zeros(n, dtype=np.float64))
