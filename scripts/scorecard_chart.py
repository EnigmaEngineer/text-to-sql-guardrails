"""Draw the scorecard. One measurement, two panels, no new numbers.

    python3 scripts/scorecard_chart.py --db /tmp/wh.duckdb --out docs/scorecard.png

The left panel is the pooled score for the two degenerate arms and the real one, with the
floor drawn across it. The point of the picture is the shaded region, which is the part of
every bar that a system with no guardrails at all already has.

The right panel is the layer ablation. Bars that do not move are the finding.

Everything here comes out of `evals/scorecard.py`. Nothing is computed in this file, per
the standing rule that a number deciding anything lives where a mutant can reach it.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import cost, guard  # noqa: E402
from evals import scorecard  # noqa: E402
from warehouse import catalog  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUESTIONS = os.path.join(ROOT, "evals", "questions.jsonl")


def main(db_path, out_path):
    import duckdb
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    con = duckdb.connect(db_path, read_only=True)
    tables = catalog.read(con)
    ceiling = cost.warehouse_ceiling(con)
    with open(QUESTIONS, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    n = len(rows)

    arms = scorecard.arms(con, tables, rows, ceiling, guard.approve)
    ablation = scorecard.ablate(con, tables, rows, ceiling, guard.approve)
    floor = [c for c in arms if c.arm == "approve everything"][0].pooled("any")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 4.6))

    labels = [c.arm for c in arms]
    values = [c.pooled("any") for c in arms]
    ax1.barh(labels, values, color=["#b0b0b0", "#b0b0b0", "#2f6f4f"])
    ax1.axvspan(0, floor, color="#d94f4f", alpha=0.12)
    ax1.axvline(floor, color="#d94f4f", linestyle="--", linewidth=1.4)
    ax1.text(floor - 0.4, -0.42, "no guardrails at all: %d of %d" % (floor, n),
             color="#a03030", ha="right", fontsize=9)
    for i, v in enumerate(values):
        ax1.text(v + 0.3, i, "%d of %d" % (v, n), va="center", fontsize=9)
    ax1.set_xlim(0, n + 4)
    ax1.set_xlabel("questions scored correct, out of %d" % n)
    ax1.set_title("The pooled number, and how much of it is free")
    ax1.invert_yaxis()

    ab_labels = [c.arm for c in ablation]
    ab_values = [c.pooled("any") for c in ablation]
    ab_raised = [len(c.raised()) for c in ablation]
    colours = ["#2f6f4f" if r == 0 else "#c98a2b" for r in ab_raised]
    ax2.barh(ab_labels, ab_values, color=colours)
    ax2.axvline(floor, color="#d94f4f", linestyle="--", linewidth=1.4)
    for i, (v, r) in enumerate(zip(ab_values, ab_raised)):
        note = "%d of %d" % (v, n)
        if r:
            note += "   %d raised" % r
        ax2.text(v + 0.3, i, note, va="center", fontsize=9)
    ax2.set_xlim(0, n + 8)
    ax2.set_xlabel("questions scored correct, out of %d" % n)
    ax2.set_title("Take a layer away")
    ax2.invert_yaxis()

    fig.suptitle(
        "text-to-sql-guardrails, the scorecard. There is no accuracy number here, "
        "because nothing has called a model.", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(out_path, dpi=130)
    print("wrote %s" % out_path)
    con.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(ROOT, "warehouse", "retail.duckdb"))
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "scorecard.png"))
    a = ap.parse_args()
    sys.exit(main(a.db, a.out))
