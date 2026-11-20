"""In-memory sqlite3 table with 20k rows: pages live in C malloc, not pymalloc."""

import sqlite3

KEEP = []


def run(scale=1.0):
    n = int(20000 * scale)
    db = sqlite3.connect(":memory:")
    db.execute("create table t(a integer, b text)")
    db.executemany("insert into t values (?, ?)", [(i, "x" * 50) for i in range(n)])
    db.commit()
    KEEP.append(db)
