"""Draw the retrieval result. Reads the report's json, computes nothing of its own.

    python3 scripts/retrieval_report.py --db /tmp/wh.duckdb --json /tmp/r.json
    python3 scripts/retrieval_chart.py --json /tmp/r.json --out docs/retrieval_cost.png

The picture is the argument. Every retriever sits below and to the left of the point that
sends the whole schema, and none of them reaches it.
"""

import argparse
import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

STYLE = {
    "lexical": ("o", "-"),
    "lexical+join": ("s", "-"),
    "dense": ("o", "--"),
    "dense+join": ("s", "--"),
}


def main(json_path, out_path):
    with open(json_path) as fh:
        doc = json.load(fh)
    full = doc["full_schema_chars"]

    series = {}
    for row in doc["rows"]:
        series.setdefault(row["retriever"], []).append(row)

    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    for name in sorted(series):
        points = sorted(series[name], key=lambda r: r["mean_chars"])
        marker, line = STYLE.get(name, ("o", "-"))
        ax.plot(
            [p["mean_chars"] for p in points],
            [p["complete"] / p["n"] for p in points],
            marker=marker, linestyle=line, label=name,
        )
        for p in points:
            if p["k"] in (1, 8):
                ax.annotate("k=%d" % p["k"], (p["mean_chars"], p["complete"] / p["n"]),
                            textcoords="offset points", xytext=(4, -10), fontsize=7)

    n = doc["rows"][0]["n"]
    ax.scatter([full], [1.0], marker="*", s=200, zorder=5, color="black")
    ax.annotate("send the whole schema\n%s chars" % "{:,}".format(full), (full, 1.0),
                textcoords="offset points", xytext=(-118, -6), fontsize=8)
    ax.set_xlabel("mean schema characters put in the prompt")
    ax.set_ylabel("questions whose whole table set was retrieved")
    ax.set_title("Retrieval buys nothing on a %s character schema (n=%d questions)"
                 % ("{:,}".format(full), n))
    ax.set_ylim(0, 1.08)
    ax.set_xlim(0, full * 1.08)
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    print("wrote %s" % out_path)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--out", default="docs/retrieval_cost.png")
    a = ap.parse_args()
    sys.exit(main(a.json, a.out))
