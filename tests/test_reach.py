"""Checks on the reach measurement, including the control that caught the day's mistake.

`evals/reach.py` produces the number the correction loop leads with, so it gets tests rather than a
report script and a hope. The two that matter are the suspect rule and the one asserting
that the hand written queries name only real objects. Either would have caught the typo
that made the report announce PII coverage this project does not have.
"""

from agent import cost, guard, validate
from evals import gold, reach
from tests.harness import eq, true
from warehouse import catalog


class _Verdict:
    def __init__(self, allowed, reason="", detail=""):
        self.allowed = allowed
        self.reason = reason
        self.detail = detail


def check_the_plausible_queries_cover_every_refuse_question():
    ids = {r["id"] for r in gold.load() if r["expect"] == "refuse"}
    eq(sorted(reach.PLAUSIBLE), sorted(ids), "one plausible query per refuse question")


def check_every_plausible_query_names_only_real_objects(ctx):
    """The control. A name error here reads as a refusal and inflates coverage.

    Runs each hand written query through the validator and fails on a name error, except
    for the question tagged `hallucination`, where naming something absent is the point.
    On its first run this failed on q026 and q027, which asked two tables for a
    `customer_name` and an `employee_name` that neither has.
    """
    tables = catalog.read(ctx.con)
    allowed_to_be_absent = {
        r["id"] for r in gold.load() if "hallucination" in r.get("tags", ())
    }
    true(allowed_to_be_absent, "the eval set has a hallucination question to exempt")

    for qid, sql in sorted(reach.PLAUSIBLE.items()):
        if qid in allowed_to_be_absent:
            continue
        report = validate.check(ctx.con, tables, sql)
        names = [f for f in report.findings if f.code in reach.NAME_ERROR_CODES]
        eq(names, [], "%s names something that is not in the catalog" % qid)


def check_the_hallucination_question_really_does_name_something_absent(ctx):
    """The exemption above is only safe if the thing it exempts is still tested."""
    tables = catalog.read(ctx.con)
    absent = [
        qid for qid in reach.PLAUSIBLE
        if qid in {r["id"] for r in gold.load() if "hallucination" in r.get("tags", ())}
    ]
    eq(len(absent), 1, "exactly one hallucination question")
    report = validate.check(ctx.con, tables, reach.PLAUSIBLE[absent[0]])
    codes = [f.code for f in report.findings]
    true("unknown_column" in codes, "%s should name an absent column, got %s" % (absent[0], codes))


def check_a_name_error_outside_the_exemption_is_flagged_as_suspect():
    """Fed a stub, so the bookkeeping is checked without the warehouse.

    Every non hallucination question is refused for `unknown_column`, which is what the
    bug looked like. All of them should come back suspect and none should count as a
    real refusal that anyone celebrates.
    """
    rows = [{"id": qid, "expect": "refuse", "tags": []} for qid in reach.PLAUSIBLE]
    stub = lambda con, tables, sql, ceiling: _Verdict(False, "unknown_column", "typo")
    measured = reach.measure(None, None, rows, 1, stub)
    eq(len(measured.suspect), len(reach.PLAUSIBLE), "every one flagged")
    eq(measured.approved, [], "none approved")


def check_a_hallucination_tag_exempts_a_name_error():
    """`measure` walks all of PLAUSIBLE, so the other seven are still suspect here.

    Asserting an empty list would have been the easier check and it would have been
    wrong. The exemption is per question and the assertion has to be too.
    """
    rows = [{"id": "q030", "expect": "refuse", "tags": ["hallucination"]}]
    stub = lambda con, tables, sql, ceiling: _Verdict(False, "unknown_column", "absent")
    measured = reach.measure(None, None, rows, 1, stub)
    flagged = [qid for qid, _detail in measured.suspect]
    true("q030" not in flagged, "the hallucination question is exempt")
    eq(len(flagged), len(reach.PLAUSIBLE) - 1, "and nothing else is")


def check_a_gate_refusal_is_never_suspect():
    """`not_a_read` cannot be a typo, so it is never in doubt."""
    rows = [{"id": qid, "expect": "refuse", "tags": []} for qid in reach.PLAUSIBLE]
    stub = lambda con, tables, sql, ceiling: _Verdict(False, "not_a_read", "a write")
    measured = reach.measure(None, None, rows, 1, stub)
    eq(measured.suspect, [], "a write refusal is not a name error")
    eq(measured.refused_by_something, len(reach.PLAUSIBLE), "all refused")


def check_an_approved_query_is_counted_as_still_running():
    rows = [{"id": qid, "expect": "refuse", "tags": []} for qid in reach.PLAUSIBLE]
    stub = lambda con, tables, sql, ceiling: _Verdict(True)
    measured = reach.measure(None, None, rows, 1, stub)
    eq(len(measured.approved), len(reach.PLAUSIBLE), "all approved")
    eq(measured.refused_by_something, 0, "nothing refused")


def check_the_real_measurement_still_says_pii_runs(ctx):
    """The finding this file exists to protect, asserted against the live guard.

    Nothing in this project stops a query reading PII. If a later change
    makes that false, this check fails and somebody has to decide whether the thread
    closed or whether a rule got quietly widened.
    """
    tables = catalog.read(ctx.con)
    ceiling = cost.warehouse_ceiling(ctx.con)
    rows = gold.load()
    measured = reach.measure(ctx.con, tables, rows, ceiling, guard.approve)
    eq(measured.suspect, [], "no suspect refusals in the real run")
    for qid in ("q026", "q027"):
        true(qid in measured.approved, "%s should still run, PII is not gated" % qid)
    true("q028" in measured.approved, "q028 should still run, see the cost finding")


def check_a_refused_gold_query_is_recorded():
    """The answer key loop contributes nothing today, and it stays.

    A mutant that deleted it survived, because all 22 gold queries validate clean, so
    removing the loop changes no output. It is not unreachable. It fires the moment a
    guardrail starts refusing the answer key, which is the worst regression this repo
    can have and the one thing a coverage report must never hide. Same call as the cost
    `no_estimate` branch, tested with a stub rather than deleted.
    """
    rows = [
        {"id": "q001", "expect": "answer", "gold_sql": "SELECT 1", "tags": []},
        {"id": "q002", "expect": "answer", "gold_sql": "SELECT 2", "tags": []},
    ]
    stub = lambda con, tables, sql, ceiling: _Verdict(False, "cross_join", "regressed")
    measured = reach.measure(None, None, rows, 1, stub)
    eq(sorted(measured.by_code["cross_join"])[:2], ["q001", "q002"], "both recorded")


def check_an_unknown_table_is_treated_as_a_possible_typo():
    """A mutant narrowed NAME_ERROR_CODES to unknown_column alone and survived.

    No plausible query names a missing table today, so nothing exercised the second
    entry. It is there for the same reason as the first. A hand written query that
    fat-fingers a table name would otherwise be counted as a refusal.
    """
    rows = [{"id": qid, "expect": "refuse", "tags": []} for qid in reach.PLAUSIBLE]
    stub = lambda con, tables, sql, ceiling: _Verdict(False, "unknown_table", "no such table")
    measured = reach.measure(None, None, rows, 1, stub)
    eq(len(measured.suspect), len(reach.PLAUSIBLE), "an invented table is suspect too")


def check_most_of_the_policy_is_never_reached(ctx):
    """The day's headline, pinned so it cannot drift without somebody noticing."""
    from tests.test_correct import refusal_codes

    tables = catalog.read(ctx.con)
    ceiling = cost.warehouse_ceiling(ctx.con)
    measured = reach.measure(ctx.con, tables, gold.load(), ceiling, guard.approve)
    codes = refusal_codes()
    reached = len(measured.by_code)
    true(
        reached < len(codes) / 2,
        "%d of %d codes reached, the finding has changed and the README with it"
        % (reached, len(codes)),
    )
