"""200k 1 KiB bytes objects held live: blocks above pymalloc's 512 B cutoff."""

KEEP = []


def run(scale=1.0):
    n = int(200000 * scale)
    KEEP.append([bytes(1024) for _ in range(n)])
