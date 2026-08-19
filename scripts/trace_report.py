"""What the correction policy covers, what a retry costs, and which codes anything reaches.

    python3 scripts/trace_report.py --db /tmp/wh.duckdb

Three sections, and the third is the one worth reading.

**Policy.** Every refusal code the agent can produce, read out of the source by
`tests.test_correct.refusal_codes` rather than typed here, with what the policy does
about each.

**Cost.** What a retry actually costs, measured on the answer key. A trace is not free
and the number belongs next to the cap that spends it.

**Reach.** Which refusal codes anything outside the test suite has ever produced. A
policy entry for a code no real input reaches is a decision nobody has had to make.

No accuracy figure is printed anywhere here and that is deliberate. The generator is a
fixture. Numbers about the loop are real. A number about whether correction helps a model
would be a statement about `agent/generate.py` and nothing else.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import correct, cost, generate, guard, pipeline, trace as trace_mod  # noqa: E402
from evals import reach, scorecard  # noqa: E402
from tests.test_correct import refusal_codes  # noqa: E402
from warehouse import catalog  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUESTIONS = os.path.join(ROOT, "evals", "questions.jsonl")


def load_questions():
    with open(QUESTIONS, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def policy_section():
    codes = refusal_codes()
    print("POLICY, %d refusal codes read out of agent/ with ast" % len(codes))
    print("  %-20s %-8s %-6s %s" % ("code", "action", "novel", "declared in"))
    for code in sorted(codes):
        s = correct.STRATEGY[code]
        print("  %-20s %-8s %-6s %s" % (code, s.action, s.novel, ", ".join(sorted(codes[code]))))
    coached = sum(1 for s in correct.STRATEGY.values() if s.action == correct.REVISE)
    novel = len(correct.NOVEL_CODES)
    print()
    print("  coached %d of %d, not coached %d" % (coached, len(codes), len(codes) - coached))
    print("  novel   %d of %d  %s" % (novel, len(codes), ", ".join(correct.NOVEL_CODES)))
    print("  the other %d are properties of the query read against a schema the prompt" % (len(codes) - novel))
    print("  already carried in full, so the correction points rather than informs")
    return codes


BAD_COLUMN = "SELECT favourite_colour FROM retail.dim_customer"
BAD_TABLE = "SELECT * FROM retail.fct_orders"


def cost_section(con, tables, rows, ceiling, repeats=7):
    """What a retry costs, measured rather than assumed.

    Timed on the answer key, which is the only set here that all reach execution. A
    refused query never runs, so timing the loop on refusals would flatter it.

    Warmed up and repeated, and that is not ceremony. The first version of this timed
    each arm once and reported 1.20x. The first `solve` of the process pays for the
    catalog read and the planner warming, and that cost landed entirely on the single
    attempt arm because it went first. With a warmup pass discarded and seven repeats the
    answer is around 1.46x. Same shape as the torch warmup problem of 07-29, where a
    model loaded outside the timer still charged its first forward pass to the first
    query measured.

    The spread is printed rather than a single figure. On a total of about 50 ms the run
    to run noise is a real part of the answer.
    """
    gold = [r for r in rows if r["expect"] == "answer"]

    def one_pass(sequence_for):
        t0 = time.perf_counter()
        for r in gold:
            g = generate.SequenceGenerator({r["question"]: sequence_for(r)})
            t = pipeline.solve(con, r["question"], tables, g, ceiling=ceiling, max_retries=2)
            if t.ending != trace_mod.RESOLVED:
                print("  WARNING %s ended %s, not resolved" % (r["id"], t.ending))
        return time.perf_counter() - t0

    clean = lambda r: [r["gold_sql"]]
    # Two refusals then the gold query, so the whole budget is spent before an answer.
    corrected = lambda r: [BAD_COLUMN, BAD_TABLE, r["gold_sql"]]

    one_pass(clean)
    one_pass(corrected)

    singles = sorted(one_pass(clean) for _ in range(repeats))
    triples = sorted(one_pass(corrected) for _ in range(repeats))
    mid = repeats // 2
    ratio = triples[mid] / singles[mid]

    n = len(gold)
    print()
    print("COST, %d answerable questions, %d repeats after a discarded warmup, today's machine"
          % (n, repeats))
    print("  first attempt lands    median %6.1f ms  range %5.1f to %5.1f"
          % (singles[mid] * 1000, singles[0] * 1000, singles[-1] * 1000))
    print("  two corrections first  median %6.1f ms  range %5.1f to %5.1f"
          % (triples[mid] * 1000, triples[0] * 1000, triples[-1] * 1000))
    print("  a full budget costs    %.2fx a clean run, not 3x, because a refused"
          % ratio)
    print("  attempt is judged and never executed")
    return ratio


def reach_section(con, tables, rows, ceiling):
    """Print what `evals.reach` measured. The measuring lives there, not here."""
    measured = reach.measure(con, tables, rows, ceiling, guard.approve)
    codes = refusal_codes()
    unreached = measured.unreached(codes)
    n = len(reach.PLAUSIBLE)

    print()
    print("REACH, refusal codes produced by something other than a test")
    for code in sorted(measured.by_code):
        print("  %-20s %s" % (code, ", ".join(measured.by_code[code])))
    print()
    print("  reached   %d of %d" % (len(measured.by_code), len(codes)))
    print("  unreached %d  %s" % (len(unreached), ", ".join(unreached)))

    refused = measured.refused_by_something
    # The correction loop printed the matching reading as `refused - 1`. That was true on the day and
    # it was arithmetic rather than a definition. It is computed
    # from `scorecard.OWNER`, so the two readings can disagree by any amount.
    card = scorecard.score(con, tables, rows, ceiling, guard.approve, "trace_report")
    matching = card.refused("matching")
    print()
    print("  REFUSAL COVERAGE, both readings, because the repo has been quoting one")
    print("    refused by something                      %d of %d" % (refused, n))
    print("    refused by the layer its label points at  %d of %d" % (matching, n))
    for o in card.mislabelled():
        print("    %s is labelled %s and %s is what stops it" % (
            o.qid, o.refuse_reason, o.stage))
    print("    still runs: %s" % (", ".join(measured.approved) or "none"))
    if measured.suspect:
        print()
        print("  SUSPECT REFUSALS, a name error here reads as coverage and is not:")
        for qid, detail in measured.suspect:
            print("    %s  %s" % (qid, detail))
    return measured, unreached


def ending_section(con, tables):
    """Every ending, on real refusals, with the attempt each one cost."""
    good = "SELECT count(*) AS n FROM retail.dim_customer"
    bad_column = "SELECT favourite_colour FROM retail.dim_customer"
    bad_table = "SELECT * FROM retail.fct_orders"

    cases = [
        ("clean first attempt", [good]),
        ("corrected once", [bad_column, good]),
        ("two corrections", [bad_column, bad_table, good]),
        ("generator repeats itself", [bad_column, bad_column, good]),
        ("never recovers", [bad_column, bad_table, "SELECT FROM WHERE", good]),
        ("write attempt", ["DELETE FROM retail.dim_customer", good]),
        ("host file read", ["SELECT * FROM read_csv('/etc/hostname')", good]),
    ]

    print()
    print("ENDINGS, cap of 2 retries")
    print("  %-26s %-22s %s" % ("case", "ending", "attempts"))
    traces = []
    for label, answers in cases:
        g = generate.SequenceGenerator({label: answers})
        t = pipeline.solve(con, label, tables, g, max_retries=2)
        traces.append((label, t))
        print("  %-26s %-22s %d of %d" % (label, t.ending, len(t.attempts), len(answers)))
    return traces


def main(db_path, show):
    import duckdb

    con = duckdb.connect(db_path, read_only=True)
    tables = catalog.read(con)
    ceiling = cost.warehouse_ceiling(con)
    rows = load_questions()

    policy_section()
    cost_section(con, tables, rows, ceiling)
    reach_section(con, tables, rows, ceiling)
    traces = ending_section(con, tables)

    if show:
        print()
        print("=" * 78)
        for label, t in traces:
            if label == show:
                print(trace_mod.render(t))
    con.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(ROOT, "warehouse", "retail.duckdb"))
    ap.add_argument("--show", default="", help="render one trace by case label")
    a = ap.parse_args()
    sys.exit(main(a.db, a.show))
