"""The eval set, question by question, and what happens when the guard is taken apart.

    python3 scripts/scorecard_report.py --db /tmp/wh.duckdb

Day 7 of the plan asks for accuracy numbers. There is no model in this repo, so there is
no accuracy number to print and this script says so rather than printing something that
looks like one. What it prints instead is the guard scored against the frozen set, the
two degenerate arms that bracket it, and a layer ablation.

The measuring lives in `evals/scorecard.py`. This file arranges it on a page. That split
is the 08-06 rule on this program, which is that a number deciding anything belongs where
a mutant can reach it, and nothing in `tests/` imports a script.
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


def load_questions():
    with open(QUESTIONS, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def no_accuracy_section():
    print("THERE IS NO ACCURACY NUMBER IN THIS REPO AND THERE CANNOT BE ONE")
    print("  The plan for today says README with accuracy numbers on the eval set.")
    print("  Accuracy on a text to SQL set is a property of the thing writing the SQL.")
    print("  Nothing here has ever called a model. agent/generate.py ships fixtures and")
    print("  a backend that raises. A score taken with a fixture measures the fixture.")
    print("  So the guard is scored instead, and the guard is what this project is about.")


def per_question(card):
    print()
    print("EVERY QUESTION, ONE ROW")
    print("  %-6s %-8s %-16s %-9s %-9s %s" % (
        "id", "expect", "refuse_reason", "owner", "stage", "code"))
    for o in card.outcomes:
        print("  %-6s %-8s %-16s %-9s %-9s %s" % (
            o.qid, o.expect, o.refuse_reason or "-", o.owner or "-", o.stage, o.code))
    print()
    print("  the 22 answerable rows are run as their gold SQL, which is the frozen key")
    print("  the 8 refuse rows are run as HAND WRITTEN plausible SQL, see evals/reach.py")


def arms_section(con, tables, rows, ceiling):
    print()
    print("THE POOLED NUMBER, AND WHAT IT IS WORTH")
    print("  %-20s %-9s %-11s %-13s %s" % (
        "arm", "gold 22", "refused 8", "pooled any", "pooled matching"))
    cards = scorecard.arms(con, tables, rows, ceiling, guard.approve)
    n = len(rows)
    for c in cards:
        print("  %-20s %5d/22 %8d/8 %8d/%d %5.1f%% %6d/%d %5.1f%%" % (
            c.arm, c.approved_gold(), c.refused("any"),
            c.pooled("any"), n, 100.0 * c.pooled("any") / n,
            c.pooled("matching"), n, 100.0 * c.pooled("matching") / n))
    open_arm = [c for c in cards if c.arm == "approve everything"][0]
    real = [c for c in cards if c.arm == "this repo"][0]
    free = 100.0 * open_arm.pooled("any") / n
    print()
    print("  A system with no guardrails at all scores %.1f percent here, because it" % free)
    print("  approves every correct query and there are 22 of those against 8 of the")
    print("  other kind. That is the floor and it is measured rather than argued.")
    print("  Every guardrail in this repo put together moved it by %d questions." % (
        real.pooled("any") - open_arm.pooled("any")))
    return real


def refusal_section(real, n_refuse):
    k = real.refused("any")
    bound = scorecard.lower_bound(k, n_refuse)
    print()
    print("THE HALF THAT IS NOT IN SAMPLE")
    print("  The 22 approvals are pinned by three checks that fail the build if any")
    print("  layer refuses a gold query, so that half records a green test rather than")
    print("  a measurement. The 8 refusals are the only part that could have gone badly.")
    print()
    print("    refused by something                      %d of %d" % (k, n_refuse))
    print("    refused by the layer its label points at  %d of %d" % (
        real.refused("matching"), n_refuse))
    print("    exact one sided 95%% lower bound on %d of %d   %.3f" % (k, n_refuse, bound))
    print()
    print("  %d of %d reads as %.1f percent and eight observations do not support a" % (
        k, n_refuse, 100.0 * k / n_refuse))
    print("  percentage. The bound is what the count licenses.")
    for o in real.mislabelled():
        print("    %s refused at %s and its label points at %s" % (o.qid, o.stage, o.owner))
    for o in real.unowned():
        print("    %s has no owning layer at all, %s is on no day of the plan" % (
            o.qid, o.refuse_reason))


def ablation_section(con, tables, rows, ceiling):
    print()
    print("TAKE A LAYER AWAY AND SCORE IT AGAIN")
    print("  %-15s %-8s %-10s %-12s %-8s %s" % (
        "layers", "gold 22", "refused 8", "matching 8", "raised", "pooled any"))
    cards = scorecard.ablate(con, tables, rows, ceiling, guard.approve)
    n = len(rows)
    for c in cards:
        print("  %-15s %5d/22 %7d/8 %9d/8 %7d %7d/%d" % (
            c.arm, c.approved_gold(), c.refused("any"), c.refused("matching"),
            len(c.raised()), c.pooled("any"), n))
    print()
    for c in cards:
        for o in c.raised():
            print("  RAISED  %-15s %-6s %s: %s" % (c.arm, o.qid, o.code, o.error[:60]))
    print()
    print("  A raised exception is counted wrong on both halves. It refused nothing and")
    print("  it took the caller with it, and an ablation that scored a crash as coverage")
    print("  would report the layer it just removed as unnecessary.")
    return cards


def main(db_path, json_path):
    import duckdb

    con = duckdb.connect(db_path, read_only=True)
    tables = catalog.read(con)
    ceiling = cost.warehouse_ceiling(con)
    rows = load_questions()
    n_refuse = sum(1 for r in rows if r["expect"] != "answer")

    no_accuracy_section()
    real = arms_section(con, tables, rows, ceiling)
    per_question(real)
    refusal_section(real, n_refuse)
    ablation = ablation_section(con, tables, rows, ceiling)

    if json_path:
        payload = {
            "arms": [
                {"arm": c.arm, "gold_approved": c.approved_gold(),
                 "refused_any": c.refused("any"), "refused_matching": c.refused("matching"),
                 "raised": len(c.raised()), "pooled_any": c.pooled("any"),
                 "pooled_matching": c.pooled("matching")}
                for c in scorecard.arms(con, tables, rows, ceiling, guard.approve) + ablation
            ],
            "questions": [
                {"id": o.qid, "expect": o.expect, "refuse_reason": o.refuse_reason,
                 "owner": o.owner, "stage": o.stage, "code": o.code}
                for o in real.outcomes
            ],
            "lower_bound": scorecard.lower_bound(real.refused("any"), n_refuse),
        }
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        print()
        print("wrote %s" % json_path)

    con.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(ROOT, "warehouse", "retail.duckdb"))
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    sys.exit(main(a.db, a.json))
