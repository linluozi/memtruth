"""numpy.zeros(64 MiB) with every page written: the falsification twin of numpy_zeros.

Keeping this pair in the same harness is the point: same allocation, same size,
same library -- only the touch pattern differs, and the verdict must flip.
"""

import numpy as np

KEEP = []


def run(scale=1.0):
    n = int(64 * 1024 * 1024 * scale // 8)
    arr = np.zeros(n, dtype=np.float64)
    arr.fill(1.0)  # force a write to every page
    KEEP.append(arr)
