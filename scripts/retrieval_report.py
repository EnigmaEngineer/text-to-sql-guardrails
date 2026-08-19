"""Measure the retrieval layer against the frozen eval set.

    python3 scripts/retrieval_report.py --db /tmp/p10/wh.duckdb

For each scorer and each k it reports two things. The share of questions whose whole
required table set was retrieved. And what the selected schema text costs in characters
against sending everything.

The point of the run is to answer the question adr-0004 left open. Does this layer earn
its place on a schema this small.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evals import freeze, gold, power  # noqa: E402
from retrieval import dense, graph, lexical, relevance, select  # noqa: E402
from warehouse import catalog  # noqa: E402

KS = (1, 2, 3, 4, 5, 8)


def _hits(retriever, rows, rel, k):
    return [1 if rel[r["id"]] <= retriever.select(r["question"], k) else 0
            for r in rows if r["id"] in rel]


def _compare(runs, rows, rel, results):
    """Every pairwise comparison at the largest k, with the p value beside it.

    Computed here rather than written into prose. A count in a sentence goes stale the
    moment the thing it counts changes, and I have published two wrong
    headline numbers that way already.
    """
    k = KS[-1]
    print("paired comparisons at k=%d, exact sign flip test" % k)
    vectors = {r.name: _hits(r, rows, rel, k) for r in runs}
    names = sorted(vectors)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            res = power.paired_permutation(vectors[a], vectors[b])
            verdict = "decided" if res["p"] < 0.05 else "underpowered"
            print("   %-14s vs %-14s %2d differ  net %+d  p %.4f  floor %.4f  %s"
                  % (b, a, res["differing"], res["net"], res["p"], res["p_floor"],
                     verdict))
    print()


def _dump(path, full, results):
    """One measurement, two renderings.

    The chart reads this file rather than recomputing anything. Two scripts measuring the
    same thing separately is how a README ends up publishing a number no code produces,
    which happened twice on the previous project.
    """
    out = {
        "full_schema_chars": full,
        "rows": [
            {"retriever": name, "k": k, "complete": res["complete"], "n": res["n"],
             "table_recall": res["table_recall"], "mean_chars": chars,
             "chars_saved": full - chars}
            for (name, k), (res, chars) in sorted(results.items())
        ],
    }
    with open(path, "w") as fh:
        json.dump(out, fh, indent=2)
        fh.write("\n")
    print("wrote %s" % path)


def main(db_path, with_dense=True, json_path=None):
    import duckdb

    freeze.verify()
    con = duckdb.connect(db_path, read_only=True)
    tables = catalog.read(con)
    rows = gold.answerable()
    rel = relevance.gold_relevance(con, rows)
    links = graph.edges(tables, graph.primary_keys(con))

    full = len(catalog.render_all(tables))
    print("%d tables, whole schema renders in %d chars" % (len(tables), full))
    unused = relevance.coverage(rel, [t.name for t in tables])
    print("tables no gold query touches: %d  %s" % (len(unused), ", ".join(unused)))
    hit, total = graph.edge_agreement(links, graph.gold_edges(con, rows))
    print("inferred join edges cover %d of %d gold table pairs" % (hit, total))
    print()

    scorers = [lexical.Scorer(tables)]
    if not with_dense:
        print("SKIPPED the dense scorer, asked for with --no-dense")
        print()
    elif not dense.available():
        # a report that silently drops half its rows is the shape of failure this
        # program has hit twice, where a check passed because it checked nothing
        print("SKIPPED the dense scorer, torch and sentence-transformers are not")
        print("installed. See requirements-dense.txt. The table below is lexical only.")
        print()
    else:
        t0 = time.time()
        scorers.append(dense.Scorer(tables))
        print("dense scorer built and warmed in %.1fs" % (time.time() - t0))
        print()

    runs = []
    for scorer in scorers:
        for hops in (0, 1):
            runs.append(select.Retriever(scorer, links, hops))

    print("%-16s %3s %10s %8s %8s" % ("retriever", "k", "complete", "recall", "chars"))
    results = {}
    for retriever in runs:
        for k in KS:
            res = select.complete_at_k(retriever, rows, rel, k)
            chars = 0
            for row in rows:
                if row["id"] in rel:
                    chars += select.prompt_chars(
                        tables, retriever.select(row["question"], k)
                    )
            mean_chars = chars / res["n"]
            results[(retriever.name, k)] = (res, mean_chars)
            print(
                "%-16s %3d %6d/%-3d %8.3f %8.0f"
                % (
                    retriever.name,
                    k,
                    res["complete"],
                    res["n"],
                    res["table_recall"],
                    mean_chars,
                )
            )
    print()
    print("send everything      %6d/%-3d %8.3f %8d" % (len(rel), len(rel), 1.0, full))
    print()

    _compare(runs, rows, rel, results)

    best = max(results.items(), key=lambda kv: (kv[1][0]["complete"], -kv[1][1]))
    (name, k), (res, mean_chars) = best
    saved = full - mean_chars
    print("best complete rate: %s at k=%d, %d of %d" % (name, k, res["complete"], res["n"]))
    print("   it costs %.0f chars against %d for the whole schema" % (mean_chars, full))
    print("   so it saves %.0f chars, %.1f percent, and gives up %d question(s)"
          % (saved, 100.0 * saved / full, res["n"] - res["complete"]))
    if res["complete"] < res["n"]:
        print("tables it misses most:")
        for table, count in select.missed_tables(res):
            print("   %-24s missed on %d questions" % (table, count))
    print()
    print(power.describe(len(gold.load()), len(rel)))
    if json_path:
        _dump(json_path, full, results)
    con.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="warehouse/retail.duckdb")
    ap.add_argument("--no-dense", action="store_true")
    ap.add_argument("--json", default=None, help="write the measurements for the chart")
    a = ap.parse_args()
    sys.exit(main(a.db, not a.no_dense, a.json))
