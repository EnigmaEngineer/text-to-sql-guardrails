"""Build the warehouse from schema.sql plus the seeded generator.

    python3 scripts/build_warehouse.py --db /tmp/p10/wh.duckdb

The database must live outside the Projects folder when this runs in the sandbox. A
DuckDB checkpoint unlinks its write ahead log and the mount refuses unlink, so a build
straight onto warehouse/ dies. The repo default is still warehouse/retail.duckdb because
that is the right place on a laptop.
"""

import argparse
import csv
import os
import shutil
import tempfile
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import duckdb

from warehouse import seed

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_SQL = os.path.join(HERE, "warehouse", "schema.sql")


def build(db_path, quiet=False):
    if os.path.exists(db_path):
        os.remove(db_path)
    con = duckdb.connect(db_path)
    con.execute(open(SCHEMA_SQL).read())

    tables = seed.build()
    t0 = time.time()
    total = 0
    # executemany over 200k rows takes minutes here. CSV plus COPY takes under a second.
    staging = tempfile.mkdtemp(prefix="whload-")
    try:
        for name, rows in tables.items():
            if not rows:
                continue
            path = os.path.join(staging, name + ".csv")
            with open(path, "w", newline="") as fh:
                csv.writer(fh).writerows(rows)
            con.execute(
                "COPY retail.%s FROM '%s' (FORMAT CSV, HEADER FALSE, NULLSTR '')" % (name, path)
            )
            total += len(rows)
            if not quiet:
                print("%-28s %8d" % (name, len(rows)))
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    con.close()
    elapsed = time.time() - t0
    if not quiet:
        print("%-28s %8d rows in %.2fs" % ("TOTAL", total, elapsed))
    return total, elapsed


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(HERE, "warehouse", "retail.duckdb"))
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    build(a.db, a.quiet)
