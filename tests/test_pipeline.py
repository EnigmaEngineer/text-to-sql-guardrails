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
       ["prompt", "generate", "parse", "gate", "validate", "execute"],
       "steps recorded in order")


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
    """The target path is unique per run, and that is not tidiness.

    It used to be a fixed name under /tmp. During the day 4 mutation run a mutant that
    executed a refused verdict really did write 4,001 customer emails to it, and the file
    then made every later mutant look killed, including the control. A test that asserts
    a fixed path is absent passes once and then fails forever for reasons that have
    nothing to do with the code.
    """
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as work:
        target = os.path.join(work, "should-not-write.csv")
        a = run_with(
            ctx,
            "list emails",
            "SELECT 1 AS ok; COPY (SELECT customer_email FROM retail.dim_customer) "
            "TO '%s' (FORMAT CSV)" % target,
        )
        eq(a.outcome, "refused", "outcome")
        # `not_a_read` and not `multiple_statements`. The serializer fails on the COPY
        # before the statement count is reached. See the note in tests/test_role.py.
        eq(a.detail, "not_a_read", "reason")
        true(not os.path.exists(target), "nothing written")


def check_valid_sql_that_the_database_rejects_is_failed_not_refused(ctx):
    """Both layers approve it and execution still fails. Two different problems.

    Until day 4 this used a bad column name, which was a fair example while nothing
    checked names. Static validation catches that now, so the case moved and the test
    had to move with it rather than being deleted. A cast that only fails on the data
    is the honest remaining example. `agent.validate` checks that names exist and has
    no opinion about types, which is the boundary this pins.
    """
    a = run_with(
        ctx,
        "bad cast",
        "SELECT CAST(customer_email AS INTEGER) AS n FROM retail.dim_customer",
    )
    eq(a.outcome, "failed", "outcome")
    eq(a.steps[-1]["step"], "execute", "reached execution")
    true("Conversion Error" in a.detail, "error is a runtime conversion: %s" % a.detail)


def check_a_bad_column_is_now_refused_before_execution(ctx):
    """The case the check above used to hold. It is a static problem now."""
    a = run_with(ctx, "bad column", "SELECT no_such_column FROM retail.dim_customer")
    eq(a.outcome, "refused", "outcome")
    eq(a.detail, "unknown_column", "reason")
    eq(a.steps[-1]["step"], "validate", "stopped at validation")


def check_a_host_file_read_is_refused_by_validation_not_the_gate(ctx):
    """The day 4 finding, at the pipeline level.

    The gate step records ok because the parser really did approve it. The validate step
    is the one that says no. Asserting both matters, because a trace that blamed the
    gate would send day 6 back to the model with the wrong correction.
    """
    a = run_with(ctx, "read a file", "SELECT * FROM read_csv('/etc/hostname')")
    eq(a.outcome, "refused", "outcome")
    eq(a.detail, "table_function", "reason")
    steps = {s["step"]: s["ok"] for s in a.steps}
    eq(steps["gate"], True, "the gate approved it")
    eq(steps["validate"], False, "validation refused it")


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


def check_answer_is_one_attempt_and_never_loops(ctx):
    """`solve` owns the loop. `answer` stayed a single attempt and that is the boundary.

    Day 6 could have grown a retry inside this function. Keeping the loop outside means
    every caller that wants one attempt still gets exactly one, and the retry policy
    lives in one place rather than behind a default argument. `tests/test_trace.py`
    covers the loop.
    """
    a = run_with(ctx, "delete things", "DELETE FROM retail.dim_customer")
    eq(len([s for s in a.steps if s["step"] == "generate"]), 1, "generated exactly once")


def check_the_attempt_serialises(ctx):
    import json

    a = run_with(ctx, "how many customers", "SELECT count(*) AS n FROM retail.dim_customer")
    payload = json.loads(json.dumps(a.as_dict()))
    eq(payload["outcome"], "answered", "round trip")
    eq(payload["row_count"], 1, "row count rather than rows")
