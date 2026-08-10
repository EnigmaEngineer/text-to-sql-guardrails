"""Draw the day 4 result. Reads the report's json, computes nothing of its own.

    python3 scripts/validation_report.py --db /tmp/p10/wh.duckdb --json /tmp/v.json
    python3 scripts/validation_chart.py --json /tmp/v.json --out docs/gate_vs_validation.png

One row per probe, coloured by which layer stopped it. The bar that matters is the middle
colour. Every one of those is a query the day 3 gate approved and the database ran.
"""

import argparse
import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

GATE = "#4c6ef5"
VALIDATION = "#e8590c"
ALLOWED = "#adb5bd"


def main(json_path, out_path):
    with open(json_path) as fh:
        doc = json.load(fh)

    probes = doc["probes"]
    labels, colours, marks = [], [], []
    for p in probes:
        labels.append(p["label"])
        if not p["gate_allows"]:
            colours.append(GATE)
            marks.append("gate")
        elif not p["validation_ok"]:
            colours.append(VALIDATION)
            marks.append("validation")
        else:
            colours.append(ALLOWED)
            marks.append("allowed")

    fig, ax = plt.subplots(figsize=(9, 6.5))
    y = range(len(labels))
    ax.barh(list(y), [1] * len(labels), color=colours, height=0.72)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xticks([])
    ax.set_xlim(0, 1.55)

    for i, p in enumerate(probes):
        note = p["if_only_the_gate"] or "never ran"
        ax.text(1.02, i, note, va="center", fontsize=7, color="#495057")

    handles = [
        plt.Rectangle((0, 0), 1, 1, color=GATE),
        plt.Rectangle((0, 0), 1, 1, color=VALIDATION),
        plt.Rectangle((0, 0), 1, 1, color=ALLOWED),
    ]
    # Below the axes. Inside the plot it sat on top of the last probe's annotation, which
    # is the one saying a semicolon in a string literal is fine.
    ax.legend(
        handles,
        [
            "refused by the day 3 parser gate",
            "approved by the gate, refused by day 4 validation",
            "approved by both, correctly",
        ],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.03),
        ncol=1,
        fontsize=8,
        frameon=False,
    )
    ax.set_title(
        "%d probe queries. The gate alone approves %d of them.\n"
        "Static validation refuses %d of those. Text on the right is what ran without it."
        % (doc["probe_count"], doc["gate_allowed"], doc["validation_caught"]),
        fontsize=10,
        loc="left",
    )
    for side in ("top", "right", "bottom"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print("wrote %s" % out_path)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "docs", "gate_vs_validation.png"))
    args = ap.parse_args()
    sys.exit(main(args.json, args.out))
