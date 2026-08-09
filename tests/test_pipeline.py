"""Checks on the end to end attempt.

Every outcome in the closed set gets a case. An outcome with no test is an outcome that
can be produced by accident.
"""

from agent import generate, pipeline
from tests.harness import eq, true
from warehouse import catalog


def run_with(ctx, question, answer_text):
    tables = catalog.read(ctx.con)
    g = generate.ScriptedGenerator({question: answer_text})
    return pipeline.answer(ctx.con, question, tables, g)


def check_a_good_query_is_answered(ctx):
    a = run_with(ctx, "how many customers", "SELECT count(*) AS n FROM retail.dim_customer")
    eq(a.outcome, "answered", "outcome")
    eq(a.rows, ((4000,),), "rows")
    eq([s["step"] for s in a.steps],
       ["prompt", "generate", "parse", "gate", "execute"], "steps recorded in order")


def check_a_refusal_is_recorded_as_such(ctx):
    a = run_with(ctx, "give up", "CANNOT_ANSWER")
    eq(a.outcome, "cannot_answer", "outcome")
    eq(a.sql, "", "no sql")
    eq([s["step"] for s in a.steps], ["prompt", "generate", "parse"], "stops after parse")


def check_a_write_is_refused_by_the_gate(ctx):
    a = run_with(ctx, "delete things", "DELETE FROM retail.dim_customer")
    eq(a.outcome, "refused", "outcome")
    eq(a.detail, "not_a_read", "reason")
    eq(a.steps[-1]["step"], "gate", "stopped at the gate")
    true(not a.steps[-1]["ok"], "gate step marked failed")


def check_the_stacked_exfiltration_is_refused_end_to_end(ctx):
    a = run_with(
        ctx,
        "list emails",
        "SELECT 1 AS ok; COPY (SELECT customer_email FROM retail.dim_customer) "
        "TO '/tmp/pipeline-should-not-write.csv' (FORMAT CSV)",
    )
    eq(a.outcome, "refused", "outcome")
    # `not_a_read` and not `multiple_statements`. The serializer fails on the COPY before
    # the statement count is reached. See the note in tests/test_role.py.
    eq(a.detail, "not_a_read", "reason")
    import os
    true(not os.path.exists("/tmp/pipeline-should-not-write.csv"), "nothing written")


def check_valid_sql_that_the_database_rejects_is_failed_not_refused(ctx):
    """The gate approves it and execution does not. Two different problems.

    Collapsing these would hide the case where the gate lets through something that
    cannot run, which is the interesting failure rather than the boring one.
    """
    a = run_with(ctx, "bad column", "SELECT no_such_column FROM retail.dim_customer")
    eq(a.outcome, "failed", "outcome")
    eq(a.steps[-1]["step"], "execute", "reached execution")
    true("no_such_column" in a.detail, "error names the column")


def check_unparseable_sql_is_refused_at_the_gate(ctx):
    """Never reaches the database. The gate parses before anything runs."""
    a = run_with(ctx, "nonsense", "SELECT FROM WHERE")
    eq(a.outcome, "refused", "outcome")
    eq(a.detail, "unparseable", "reason")
    eq([s["step"] for s in a.steps], ["prompt", "generate", "parse", "gate"], "no execute step")


def check_a_generator_error_does_not_escape(ctx):
    tables = catalog.read(ctx.con)
    a = pipeline.answer(ctx.con, "unscripted", tables, generate.ScriptedGenerator({}))
    eq(a.outcome, "failed", "outcome")
    eq(a.steps[-1]["step"], "generate", "failed at generate")


def check_there_is_no_retry_yet(ctx):
    """Day 6 owns the self correction loop. Pinned so nobody thinks it already exists.

    An empty loop written today would make the trace look complete and would make day 6
    a rename rather than a build.
    """
    a = run_with(ctx, "delete things", "DELETE FROM retail.dim_customer")
    eq(len([s for s in a.steps if s["step"] == "generate"]), 1, "generated exactly once")


def check_the_attempt_serialises(ctx):
    import json

    a = run_with(ctx, "how many customers", "SELECT count(*) AS n FROM retail.dim_customer")
    payload = json.loads(json.dumps(a.as_dict()))
    eq(payload["outcome"], "answered", "round trip")
    eq(payload["row_count"], 1, "row count rather than rows")
