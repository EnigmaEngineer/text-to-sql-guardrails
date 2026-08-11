"""The picture of why the metric changed.

    python3 scripts/cost_chart.py --db /tmp/p10/wh.duckdb --out docs/day5_cost_metric.png

Two panels. The left one is the choice between the two metrics, on a log axis because the
whole point is that one of them separates the answer key from a runaway query by a factor
of three and a half thousand and the other by a factor of one and a half. The right one is
the honest half, which is that the estimate the ceiling reads is not an upper bound.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import cost, guard, role

INEQUALITY = (
    "SELECT count(*) FROM retail.fct_order_line l "
    "JOIN retail.fct_web_session s ON l.quantity > s.page_views"
)


def main(db_path, out_path, scratch):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    con = role.connect(db_path)
    ceiling = cost.warehouse_ceiling(con)

    gold = []
    with open(os.path.join(root, "evals", "questions.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("expect") == "answer":
                gold.append((row["id"], row["gold_sql"]))

    peaks, scans, actuals = [], [], []
    for _qid, sql in gold:
        estimate = cost.read_plan(guard.plan_of(con, sql))
        peaks.append(estimate.peak_rows)
        scans.append(estimate.scanned_rows)
        con.execute("PRAGMA enable_profiling='json'")
        con.execute("PRAGMA profiling_output='%s'" % scratch)
        con.execute(sql).fetchall()
        con.execute("PRAGMA disable_profiling")
        with open(scratch, encoding="utf-8") as fh:
            doc = json.load(fh)
        total = [0]

        def walk(node):
            if "SCAN" in (node.get("operator_name") or ""):
                total[0] += node.get("operator_cardinality") or 0
            for child in node.get("children") or []:
                walk(child)

        walk(doc)
        actuals.append(total[0])

    runaway = cost.read_plan(guard.plan_of(con, INEQUALITY))

    fig, (left, right) = plt.subplots(1, 2, figsize=(12, 4.6))

    labels = ["answer key\nworst case", "inequality join\nday 4 approves this"]
    left.bar([0.8, 1.8], [max(scans), runaway.scanned_rows], width=0.35,
             label="sum of scan nodes", color="#9aa5b1")
    left.bar([1.2, 2.2], [max(peaks), runaway.peak_rows], width=0.35,
             label="largest node estimate", color="#2b6cb0")
    left.axhline(ceiling, color="#c53030", linestyle="--", linewidth=1.2,
                 label="ceiling %s" % format(ceiling, ","))
    left.set_yscale("log")
    left.set_xticks([1.0, 2.0])
    left.set_xticklabels(labels)
    left.set_ylabel("estimated rows, log scale")
    left.set_title("Summing the scans leaves no room for a ceiling")
    left.legend(fontsize=8, loc="upper left")

    right.scatter(actuals, scans, s=26, color="#2b6cb0")
    top = max(max(actuals), max(scans)) * 1.15
    right.plot([0, top], [0, top], color="#4a5568", linewidth=1,
               label="estimate equals reality")
    right.fill_between([0, top], [0, 0], [0, top], color="#c53030", alpha=0.07)
    under = sum(1 for e, a in zip(scans, actuals) if a and e < a)
    right.set_xlim(0, top)
    right.set_ylim(0, top)
    right.set_xlabel("rows the query really scanned")
    right.set_ylabel("rows the plan estimated")
    right.set_title("Under the line on %d of %d. The estimate is not a bound"
                    % (under, len(gold)))
    right.legend(fontsize=8, loc="upper left")

    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    con.close()
    print("wrote %s" % out_path)
    print("ceiling %d, gold peak %d, runaway peak %d, under the line %d of %d"
          % (ceiling, max(peaks), runaway.peak_rows, under, len(gold)))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join("warehouse", "retail.duckdb"))
    ap.add_argument("--out", default=os.path.join("docs", "day5_cost_metric.png"))
    ap.add_argument("--scratch", default="/tmp/p10-chart-profile.json")
    a = ap.parse_args()
    sys.exit(main(a.db, a.out, a.scratch))
