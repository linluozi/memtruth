"""re.findall over 1 MiB producing 262k tuples and 524k strings."""

import re

KEEP = []

_PATTERN = re.compile(r"([a-z]+)([0-9]+)")


def run(scale=1.0):
    reps = int(131072 * scale)
    s = "ab12cd34" * reps
    KEEP.append(_PATTERN.findall(s))
