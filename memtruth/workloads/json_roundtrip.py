"""dump+load of an 8 MiB JSON document: parser transient buffers plus results."""

import json

KEEP = []


def run(scale=1.0):
    n = int(60000 * scale)
    doc = [{"k": i, "v": "x" * 40} for i in range(n)]
    text = json.dumps(doc)
    KEEP.append(json.loads(text))
    KEEP.append(len(text))
