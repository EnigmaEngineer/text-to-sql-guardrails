"""Run the pipeline over the frozen eval set and report what it can and cannot do.

    python3 scripts/generation_report.py --db /tmp/p10/wh.duckdb

**The 22 of 22 this prints is not an accuracy number.** The generator is
`ScriptedGenerator` loaded with the frozen gold SQL, because no model is reachable from
the environment this repo is built in. What the run proves is that the prompt builds and
the output parses. The gate approves a correct query. The warehouse executes it and the
answer matches the frozen result. That is the plumbing. A model would have to write the
SQL for the number to mean anything, and the scorecard is where that happens.

The second half is the part worth reading. Eight questions in the eval set expect a
refusal, and this counts how many the guardrails built so far can actually catch.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import generate, pipeline, role
from evals import gold
from warehouse import catalog

# Which layer is capable of catching each refusal reason, and whether it exists yet.
# This is a claim about what each layer inspects, not a measurement. A cost ceiling
# cannot see PII and a column checker cannot see cost.
COVERAGE = {
    "write_operation": ("the gate, the read-only role and the single read gate", True),
    "not_in_schema": ("static validation, static validation against the catalog", True),
    "pii_export": ("not yet designed, needs a column policy", False),
    # q029 in this category is refused by the cross join rule. That is not cost
    # coverage. q028 is the same category, has no cross join, and passes everything.
    # See scripts/validation_report.py, which prints both.
    "unbounded_scan": ("the cost layer, cost estimation and the execution ceiling", False),
}

# The obvious wrong SQL for each covered question, written by hand. This demonstrates the
# guardrails. It does not measure a model, and a model asked these questions might well
# refuse on its own or produce something else entirely. Kept so the word COVERED above is
# backed by a run rather than by my say so.
NAIVE_SQL = {
    "q023": "DELETE FROM retail.fct_order_header WHERE order_status = 'cancelled'",
    "q024": "UPDATE retail.dim_customer SET loyalty_tier = 'platinum' WHERE customer_id = 1001",
    "q025": "DROP TABLE retail.fct_order_line",
    # Validation. The question asks for a score the warehouse does not hold, so the plausible
    # wrong answer is a column that does not exist rather than a write.
    "q030": "SELECT customer_id, churn_probability FROM retail.dim_customer",
}


def main(db_path):
    con = role.connect(db_path)
    tables = catalog.read(con)
    rows = gold.load()
    answerable = [r for r in rows if r["expect"] == "answer"]
    refusals = [r for r in rows if r["expect"] == "refuse"]

    scripted = generate.ScriptedGenerator({r["question"]: r["gold_sql"] for r in answerable})

    print("PLUMBING CHECK, NOT AN ACCURACY MEASUREMENT")
    print("generator: %s, replaying the frozen gold SQL" % scripted.name)
    print()

    outcomes = {}
    sizes = []
    matched = 0
    for row in answerable:
        attempt = pipeline.answer(con, row["question"], tables, scripted)
        outcomes[attempt.outcome] = outcomes.get(attempt.outcome, 0) + 1
        sizes.append(next(s for s in attempt.steps if s["step"] == "prompt")["detail"])
        if attempt.outcome == "answered":
            want = gold.canonical(con.execute(row["gold_sql"]).fetchall())
            if gold.canonical(list(attempt.rows)) == want:
                matched += 1

    for name in sorted(outcomes):
        print("  %-14s %d" % (name, outcomes[name]))
    print("  answer matches gold   %d of %d" % (matched, len(answerable)))

    chars = [int(s.split()[0]) for s in sizes]
    print()
    print("prompt characters over %d questions: min %d, mean %d, max %d"
          % (len(chars), min(chars), sum(chars) // len(chars), max(chars)))
    print("the schema block is %d of that and does not vary, because retrieval is off by "
          "default per adr-0005" % len(catalog.render_all(tables)))

    print()
    print("REFUSALS THE GUARDRAILS CAN REACH TODAY")
    covered = 0
    by_reason = {}
    for row in refusals:
        by_reason.setdefault(row["refuse_reason"], []).append(row["id"])
    for reason in sorted(by_reason):
        where, exists = COVERAGE[reason]
        ids = by_reason[reason]
        if exists:
            covered += len(ids)
        print("  %-16s %d question(s) %-8s %s"
              % (reason, len(ids), "COVERED" if exists else "open", where))
    print("  %d of %d refusal questions are reachable by anything built so far"
          % (covered, len(refusals)))

    print()
    print("the covered ones, run through the pipeline with the obvious naive SQL")
    by_id = {r["id"]: r for r in refusals}
    for qid in sorted(NAIVE_SQL):
        question = by_id[qid]["question"]
        naive = generate.ScriptedGenerator({question: NAIVE_SQL[qid]})
        attempt = pipeline.answer(con, question, tables, naive)
        print("  %-6s %-9s %s" % (qid, attempt.outcome, attempt.detail))

    con.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "warehouse", "retail.duckdb"))
    sys.exit(main(ap.parse_args().db))
