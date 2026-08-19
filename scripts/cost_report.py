"""What the cost ceiling costs, and what it buys.

    python3 scripts/cost_report.py --db /tmp/p10/wh.duckdb --json /tmp/c.json

Three tables. The answer key first, because a guardrail is judged on what it refuses that
it should not. Then the two candidate metrics side by side, because the choice between
them was a measurement and not a preference. Then the probes.

The estimate is compared against DuckDB's own profiler, which reports what each operator
really produced. That is the only way to say whether the number the ceiling reads is an
upper bound, and it is not.

Note that this **runs all 22 gold queries** to get those real numbers. That is free on a
warehouse of 208,969 rows and it would not be on a real one. This is a report, not
something the agent does per question.
"""

import argparse
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import cost, guard, role, validate
from warehouse import catalog

# Queries that are not in the eval set. The first is the reason this layer exists and the
# eval set has no question for it, so it is a probe and it is not counted as coverage.
PROBES = [
    ("q028 every row of one table", "SELECT * FROM retail.fct_web_session"),
    ("q029 comma cross join",
     "SELECT * FROM retail.fct_order_line l, retail.fct_web_session s"),
    ("inequality join",
     "SELECT count(*) FROM retail.fct_order_line l "
     "JOIN retail.fct_web_session s ON l.quantity > s.page_views"),
    ("join on a function of both sides",
     "SELECT count(*) FROM retail.dim_store a "
     "JOIN retail.dim_store b ON abs(a.store_id - b.store_id) = 1"),
    ("self join on a low cardinality column",
     "SELECT count(*) FROM retail.fct_order_header a "
     "JOIN retail.fct_order_header b ON a.order_status = b.order_status"),
    ("count answered from metadata", "SELECT count(*) FROM retail.dim_store"),
    ("an ordinary analytical question",
     "SELECT s.store_name, count(*) AS orders FROM retail.fct_order_header h "
     "JOIN retail.dim_store s ON s.store_id = h.store_id GROUP BY s.store_name"),
]


def gold_questions(root):
    out = []
    with open(os.path.join(root, "evals", "questions.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("expect") == "answer":
                out.append((row["id"], row["gold_sql"]))
    return out


def actual_operator_rows(con, sql, scratch):
    """What every operator really produced, from DuckDB's profiler. Runs the query."""
    con.execute("PRAGMA enable_profiling='json'")
    con.execute("PRAGMA profiling_output='%s'" % scratch)
    con.execute(sql).fetchall()
    con.execute("PRAGMA disable_profiling")
    with open(scratch, encoding="utf-8") as fh:
        doc = json.load(fh)
    total = [0]

    def walk(node):
        name = node.get("operator_name") or ""
        if "SCAN" in name:
            total[0] += node.get("operator_cardinality") or 0
        for child in node.get("children") or []:
            walk(child)

    walk(doc)
    return total[0]


def main(db_path, json_path, scratch):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    con = role.connect(db_path)
    tables = catalog.read(con)
    ceiling = cost.warehouse_ceiling(con)
    gold = gold_questions(root)

    print("CEILING %d rows, summed from duckdb_tables().estimated_size over retail" % ceiling)
    print()

    print("THE ANSWER KEY. Nothing here may be refused.")
    print("  %-6s %12s %12s %12s %9s" % ("id", "peak_est", "scan_est", "scan_actual", "verdict"))
    refused = []
    peaks, scan_est_max = [], []
    under = []
    for qid, sql in gold:
        estimate = cost.read_plan(guard.plan_of(con, sql))
        actual = actual_operator_rows(con, sql, scratch)
        verdict = guard.approve(con, tables, sql, ceiling)
        peaks.append(estimate.peak_rows)
        scan_est_max.append(estimate.scanned_rows)
        if actual and estimate.scanned_rows < actual:
            under.append((qid, estimate.scanned_rows, actual))
        if not verdict.allowed:
            refused.append(qid)
        print("  %-6s %12d %12d %12d %9s" % (
            qid, estimate.peak_rows, estimate.scanned_rows, actual,
            "ok" if verdict.allowed else verdict.reason,
        ))
    print()
    print("  refused: %d of %d" % (len(refused), len(gold)))
    print("  peak estimate over the answer key   %d, ceiling is %.1fx that"
          % (max(peaks), ceiling / max(peaks)))
    print("  the estimate came in UNDER what the query really scanned on %d of %d"
          % (len(under), len(gold)))
    for qid, est, act in sorted(under, key=lambda r: r[1] / r[2])[:3]:
        print("    %-6s estimated %d, scanned %d, ratio %.2f" % (qid, est, act, est / act))
    print()

    print("THE TWO CANDIDATE METRICS on the query the ceiling exists for.")
    print("  %-34s %14s %14s" % ("", "sum_of_scans", "peak_node"))
    print("  %-34s %14d %14d" % ("answer key, worst case", max(scan_est_max), max(peaks)))
    inequality = PROBES[2][1]
    ie = cost.read_plan(guard.plan_of(con, inequality))
    print("  %-34s %14d %14d" % ("inequality join", ie.scanned_rows, ie.peak_rows))
    print("  %-34s %14.2f %14.1f" % (
        "separation, higher is better",
        ie.scanned_rows / max(scan_est_max),
        ie.peak_rows / max(peaks),
    ))
    print()

    print("PROBES. Not in the eval set, so none of this is refusal coverage.")
    print("  %-38s %-10s %-18s %s" % ("probe", "day4", "cost", "peak_est"))
    probe_rows = []
    for label, sql in PROBES:
        report = validate.check(con, tables, sql)
        verdict = guard.approve(con, tables, sql, ceiling)
        try:
            peak = cost.read_plan(guard.plan_of(con, sql)).peak_rows
        except cost.NothingToEstimate:
            peak = -1
        cost_says = "ok" if verdict.allowed else (
            verdict.reason if verdict.stage == "cost" else "(%s first)" % verdict.stage
        )
        print("  %-38s %-10s %-18s %d" % (
            label, "ok" if report.ok else report.codes()[0], cost_says, peak,
        ))
        probe_rows.append({
            "probe": label, "day4": "ok" if report.ok else report.codes()[0],
            "cost": cost_says, "peak_est": peak,
        })
    print()
    print("  q028 is the honest failure. It reads one whole table at %d rows, and q009 is"
          % cost.read_plan(guard.plan_of(con, PROBES[0][1])).peak_rows)
    print("  a real question that reads the same table with no filter. Their plans cost")
    print("  the same. No ceiling separates them, so cost coverage of the eval set is 0.")
    print("  q029 was already refused by the cross join rule and is not new either.")

    payload = {
        "ceiling": ceiling,
        "gold_refused": refused,
        "gold_peak_max": max(peaks),
        "gold_scan_est_max": max(scan_est_max),
        "estimate_under_actual": [
            {"id": q, "estimated": e, "actual": a} for q, e, a in under
        ],
        "probes": probe_rows,
    }
    if json_path:
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        print()
        print("wrote %s" % json_path)
    con.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join("warehouse", "retail.duckdb"))
    ap.add_argument("--json", default=None)
    # Not a fixed path. The profiler writes this file on every query, and a fixed name in
    # a shared temp directory belongs to whoever ran the script first. When that is
    # another user the write fails inside DuckDB and surfaces as
    # "INTERNAL Error: Attempted to dereference unique_ptr that is NULL", which says
    # nothing about a path and sends you looking at the query. Same shape as the fixed
    # path that poisoned an early mutation run.
    ap.add_argument("--scratch", default=None,
                    help="where the profiler writes. A private temp file by default.")
    a = ap.parse_args()
    scratch = a.scratch
    if scratch is None:
        handle, scratch = tempfile.mkstemp(prefix="p10-profile-", suffix=".json")
        os.close(handle)
    try:
        sys.exit(main(a.db, a.json, scratch))
    finally:
        if a.scratch is None and os.path.exists(scratch):
            os.unlink(scratch)
