"""Run every gold query against the built warehouse and report on the eval set.

    python3 scripts/build_warehouse.py --db /tmp/p10/wh.duckdb
    python3 scripts/check_gold.py --db /tmp/p10/wh.duckdb

Prints the row shape of each gold answer, the collision report and the power floor. All
three are inputs to the day 1 decision about whether this eval set is usable at all.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import duckdb

from evals import collision, gold, power
from warehouse import catalog

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(db_path):
    con = duckdb.connect(db_path, read_only=True)
    rows = gold.load()
    tables = catalog.read(con)

    t0 = time.time()
    results = gold.run_gold(con, rows)
    elapsed = time.time() - t0

    print("== gold answers ==")
    for r in gold.answerable(rows):
        canon, fp = results[r["id"]]
        width = len(canon[0]) if canon else 0
        print("%s  %3d rows x %d cols  %s  %s" % (r["id"], len(canon), width, fp, r["question"][:52]))
    print("\nran %d gold queries in %.3fs" % (len(results), elapsed))

    print("\n== collisions ==")
    print(collision.report(results))

    print("\n== power ==")
    print(power.describe(len(rows), len(results)))

    print("\n== schema size ==")
    text = catalog.render_all(tables)
    print("%d tables, %d columns" % (len(tables), sum(len(t.columns) for t in tables)))
    print("whole schema rendered for a prompt: %d chars" % len(text))
    print("largest single table rendering:     %d chars"
          % max(len(t.render()) for t in tables))
    # Deliberately NOT converted to tokens. The tokeniser belongs to the model and the
    # model is a day 2 decision. Setting a token budget first was the mistake on P3.
    con.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(HERE, "warehouse", "retail.duckdb"))
    a = ap.parse_args()
    sys.exit(main(a.db))
