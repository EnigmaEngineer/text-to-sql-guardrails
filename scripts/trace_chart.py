"""One picture of the correction policy and what actually reaches it.

    python3 scripts/trace_chart.py --db /tmp/wh.duckdb --out docs/correction_policy.png

Fourteen refusal codes on the vertical. Three things said about each. Whether the policy
coaches it, whether the refusal carries a fact the prompt did not, and whether anything
outside the test suite has ever produced it.

The third column is the point of the chart. Most of the policy has never been reached by
a real input.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import correct  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(db_path, out):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    import duckdb

    from agent import cost, guard
    from evals import reach
    from tests.test_correct import refusal_codes
    from warehouse import catalog

    con = duckdb.connect(db_path, read_only=True)
    tables = catalog.read(con)
    ceiling = cost.warehouse_ceiling(con)
    with open(os.path.join(ROOT, "evals", "questions.jsonl"), encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]

    # The same measurement the report prints, from the same place, so the chart and the
    # table cannot drift apart. Nothing is recomputed here.
    measured = reach.measure(con, tables, rows, ceiling, guard.approve)
    con.close()

    codes = sorted(refusal_codes())
    coached = [correct.STRATEGY[c].action == correct.REVISE for c in codes]
    novel = [correct.STRATEGY[c].novel for c in codes]
    reached = [c in measured.by_code for c in codes]

    fig, ax = plt.subplots(figsize=(8.2, 6.0))
    columns = [
        ("coached", coached),
        ("novel", novel),
        ("reached by\nreal input", reached),
    ]

    for x, (_label, values) in enumerate(columns):
        for y, value in enumerate(values):
            ax.add_patch(
                plt.Rectangle(
                    (x - 0.42, y - 0.42), 0.84, 0.84,
                    facecolor="#2b6cb0" if value else "#e2e8f0",
                    edgecolor="white", linewidth=1.5,
                )
            )
            ax.text(
                x, y, "yes" if value else "no",
                ha="center", va="center", fontsize=8.5,
                color="white" if value else "#4a5568",
            )

    ax.set_xlim(-0.6, len(columns) - 0.4)
    ax.set_ylim(-0.6, len(codes) - 0.4)
    ax.set_xticks(range(len(columns)))
    ax.set_xticklabels([c[0] for c in columns], fontsize=9)
    ax.set_yticks(range(len(codes)))
    ax.set_yticklabels(codes, fontsize=9, family="monospace")
    ax.xaxis.set_ticks_position("top")
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(length=0)

    ax.set_title(
        "%d refusal codes. %d coached, %d novel, %d reached by anything but a test."
        % (len(codes), sum(coached), sum(novel), sum(reached)),
        fontsize=10, pad=28, loc="left",
    )
    fig.text(
        0.01, 0.015,
        "Codes read out of agent/ with ast, not listed by hand. "
        "Reach measured over the frozen eval set. p10 the correction loop.",
        fontsize=7.5, color="#4a5568",
    )
    fig.tight_layout()
    target = out if os.path.isabs(out) else os.path.join(ROOT, out)
    fig.savefig(target, dpi=150)
    print("wrote %s" % target)
    print("coached %d, novel %d, reached %d, of %d"
          % (sum(coached), sum(novel), sum(reached), len(codes)))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(ROOT, "warehouse", "retail.duckdb"))
    ap.add_argument("--out", default=os.path.join("docs", "correction_policy.png"))
    a = ap.parse_args()
    sys.exit(main(a.db, a.out))
