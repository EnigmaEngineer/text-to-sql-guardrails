"""Checks on the cost estimate and the ceiling.

The first check in this file is the one that decides whether the layer ships. A
guardrail is judged first on what it refuses that it should not, and the answer key is
the set that must never be refused. Day 4 shipped a column rule that blocked 6 of the 22
gold queries and only found out by running it over them.
"""

import json

from agent import cost, guard, role, validate
from tests.harness import eq, raises, true
from warehouse import catalog

# A join whose condition names two real tables, so day 4 approves it, and which asks the
# engine for 223 million rows. This is the query the cost layer exists for.
INEQUALITY_JOIN = (
    "SELECT count(*) FROM retail.fct_order_line l "
    "JOIN retail.fct_web_session s ON l.quantity > s.page_views"
)


def _tables(ctx):
    return catalog.read(ctx.con)


def _gold():
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = []
    with open(os.path.join(root, "evals", "questions.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("expect") == "answer":
                out.append((row["id"], row["gold_sql"]))
    return out


def check_the_ceiling_refuses_nothing_in_the_answer_key(ctx):
    """The whole answer key, through the composed guard, at the shipped ceiling."""
    tables = _tables(ctx)
    ceiling = cost.warehouse_ceiling(ctx.con)
    refused = []
    for qid, sql in _gold():
        verdict = guard.approve(ctx.con, tables, sql, ceiling)
        if not verdict.allowed:
            refused.append("%s: %s %s" % (qid, verdict.stage, verdict.reason))
    eq(refused, [], "gold queries refused at ceiling %d" % ceiling)


def check_the_answer_key_is_not_hugging_the_ceiling(ctx):
    """Headroom, not calibration. A ceiling sitting just above the answer key would be
    tuned to it, which is the thing this program keeps catching itself doing."""
    ceiling = cost.warehouse_ceiling(ctx.con)
    peak = max(
        cost.read_plan(guard.plan_of(ctx.con, sql)).peak_rows for _qid, sql in _gold()
    )
    true(ceiling >= 2 * peak, "ceiling %d against gold peak %d" % (ceiling, peak))


def check_a_join_day_four_approves_is_refused_on_cost(ctx):
    tables = _tables(ctx)
    report = validate.check(ctx.con, tables, INEQUALITY_JOIN)
    true(report.ok, "day 4 has no objection: %s" % (report.codes(),))

    verdict = guard.approve(ctx.con, tables, INEQUALITY_JOIN, cost.warehouse_ceiling(ctx.con))
    true(not verdict.allowed, "refused")
    eq(verdict.stage, "cost", "stage")
    eq(verdict.reason, "over_ceiling", "reason")
    true(verdict.judgement.estimate.peak_rows > 200_000_000, "the estimate is enormous")


def check_the_cross_join_is_refused_for_having_no_estimate_at_all(ctx):
    """And that the sum of its scans would have cleared the ceiling comfortably.

    This is the reason the rule is about unscored operators rather than about big
    numbers. The biggest number in this plan is a scan.
    """
    sql = "SELECT * FROM retail.fct_order_line l, retail.fct_web_session s"
    estimate = cost.read_plan(guard.plan_of(ctx.con, sql))
    ceiling = cost.warehouse_ceiling(ctx.con)
    true("CROSS_PRODUCT" in estimate.unscored, "unscored: %s" % (estimate.unscored,))
    true(estimate.peak_rows < ceiling, "the scan estimate alone clears the ceiling")
    eq(cost.judge(estimate, ceiling).code, "unscored_operator", "code")


def check_every_unestimated_operator_in_the_answer_key_is_on_the_safe_list(ctx):
    """Drives off the answer key, not off a list beside it.

    The 08-10 lesson. A coupling check that iterates the wrong collection is worse than
    no check, because its name is a claim. If a future schema change makes the planner
    pick an operator that carries no estimate, this fails rather than the guard quietly
    refusing a correct query.
    """
    seen = set()
    for _qid, sql in _gold():
        for node in _flatten(guard.plan_of(ctx.con, sql)):
            if node[1] is None:
                seen.add(node[0])
    true(seen, "the answer key really does contain unestimated operators")
    eq(sorted(seen - cost.UNESTIMATED_AND_SAFE), [], "unestimated operators not on the list")


def _flatten(plan):
    out = []

    def walk(nodes):
        for node in nodes:
            info = node.get("extra_info") or {}
            out.append((node.get("name"), info.get("Estimated Cardinality")))
            walk(node.get("children") or [])

    walk(plan)
    return out


def check_a_plan_where_nothing_carries_a_number_is_a_finding_and_not_a_pass():
    plan = [{"name": "MYSTERY_OP", "children": [], "extra_info": {}}]
    raises(lambda: cost.read_plan(plan), "carries an estimate", "unscoreable plan")


def check_a_scanless_plan_that_still_carries_a_number_is_scored(ctx):
    """`count(*)` on one table is answered from metadata and never scans anything.

    The first version of the rule refused this, and no gold question is a bare count on
    a single table so the answer key check stayed green while it did. Refusing a query
    for reading no table belongs to `agent.validate`, which has `no_relation` for it.
    """
    sql = "SELECT count(*) FROM retail.dim_store"
    estimate = cost.read_plan(guard.plan_of(ctx.con, sql))
    eq(estimate.scans, (), "nothing was scanned")
    true(estimate.peak_rows >= 1, "and it is still scoreable")

    verdict = guard.approve(ctx.con, _tables(ctx), sql, cost.warehouse_ceiling(ctx.con))
    true(verdict.allowed, "approved: %s %s" % (verdict.stage, verdict.reason))


def check_an_empty_plan_document_is_a_finding():
    raises(lambda: cost.read_plan([]), "empty", "empty plan")


def check_a_ceiling_of_zero_is_rejected_rather_than_applied():
    """A ceiling of zero refuses everything, which reads as a working guardrail."""
    estimate = cost.Estimate(10, 10, (("t", 10),), (), 1)
    raises(lambda: cost.judge(estimate, 0), "must be positive", "zero ceiling")
    raises(lambda: cost.judge(estimate, -5), "must be positive", "negative ceiling")


def check_the_ceiling_boundary_is_not_off_by_one():
    estimate = cost.Estimate(100, 100, (("t", 100),), (), 1)
    true(cost.judge(estimate, 100).ok, "equal to the ceiling is allowed")
    true(not cost.judge(estimate, 99).ok, "one over is refused")


def check_the_unscored_rule_wins_over_the_ceiling_rule():
    """Order inside `judge`. An unknown cost is a worse answer than a known large one."""
    estimate = cost.Estimate(10, 10, (("t", 10),), ("CROSS_PRODUCT",), 3)
    eq(cost.judge(estimate, 1).code, "unscored_operator", "code")


def check_the_ceiling_comes_off_the_warehouse_and_not_a_constant(ctx):
    ceiling = cost.warehouse_ceiling(ctx.con)
    rows = ctx.con.execute(
        "SELECT sum(estimated_size) FROM duckdb_tables() WHERE schema_name = 'retail'"
    ).fetchone()[0]
    eq(ceiling, int(rows), "ceiling")
    raises(
        lambda: cost.warehouse_ceiling(ctx.con, schema="no_such_schema"),
        "is empty",
        "a schema with nothing in it",
    )


def check_the_estimate_survives_a_round_trip_to_json(ctx):
    """Day 6 puts this in a trace. A dataclass that will not serialize is not usable."""
    verdict = guard.approve(
        ctx.con,
        _tables(ctx),
        "SELECT store_name FROM retail.dim_store WHERE store_id > 3",
        cost.warehouse_ceiling(ctx.con),
    )
    payload = json.loads(json.dumps(verdict.as_dict()))
    eq(payload["stage"], "approved", "stage")
    true(payload["cost"]["estimate"]["scans"], "the scans are in the trace")
    eq(payload["cost"]["code"], "within_ceiling", "code")


def check_no_ceiling_means_no_cost_check(ctx):
    """The earlier reports measure layers on their own and pass None. Pin that it works."""
    verdict = guard.approve(ctx.con, _tables(ctx), INEQUALITY_JOIN)
    true(verdict.allowed, "approved with no ceiling")
    true(verdict.judgement is None, "and nothing was estimated")


def check_explain_is_not_reached_before_validation_refuses(ctx):
    """`EXPLAIN` binds, and binding a table function opens the file it names.

    Measured 2026-08-11. `EXPLAIN` on `read_csv` of a path that does not exist raises
    `IOException: No files found`, so a cost layer placed in front of validation would
    do the filesystem read that validation exists to prevent. The assertion is that the
    verdict stops at validate and that no plan was taken.
    """
    verdict = guard.approve(
        ctx.con,
        _tables(ctx),
        "SELECT * FROM read_csv('/tmp/definitely-not-here-p10.csv')",
        cost.warehouse_ceiling(ctx.con),
    )
    eq(verdict.stage, "validate", "stage")
    eq(verdict.reason, "table_function", "reason")
    true(verdict.judgement is None, "cost never ran")
    # And the proof that reaching it would have hurt.
    raises(
        lambda: guard.plan_of(ctx.con, "SELECT * FROM read_csv('/tmp/definitely-not-here-p10.csv')"),
        "No files found",
        "explain binds the function",
    )


def check_a_refusal_on_cost_does_not_mark_validation_failed(ctx):
    """The trace has to say which layer refused. Adding a third layer broke this."""
    from agent import generate, pipeline

    question = "how many pairs"
    scripted = generate.ScriptedGenerator({question: INEQUALITY_JOIN})
    attempt = pipeline.answer(
        ctx.con,
        question,
        _tables(ctx),
        scripted,
        ceiling=cost.warehouse_ceiling(ctx.con),
    )
    eq(attempt.outcome, "refused", "outcome")
    steps = {s["step"]: s["ok"] for s in attempt.steps}
    true(steps["gate"], "gate passed")
    true(steps["validate"], "validation passed and must not read as a failure")
    true(not steps["cost"], "cost is the step that refused")


def check_an_unscoreable_plan_refuses_rather_than_approving(ctx):
    """The branch nothing real reaches, reached on purpose.

    A mutation run flipped this refusal to an approval and the whole suite stayed green,
    because validation refuses a scanless query before cost ever sees one and no query
    tried here produces a plan where nothing carries a number. The branch is still right
    to exist. Without it `read_plan` raises out of a `guard.execute` that is documented
    never to raise. So the answer is a stub, not a deletion.
    """
    real = guard.plan_of
    guard.plan_of = lambda con, sql, dialect=None: [
        {"name": "MYSTERY_OP", "children": [], "extra_info": {}}
    ]
    try:
        verdict = guard.approve(
            ctx.con,
            _tables(ctx),
            "SELECT store_name FROM retail.dim_store",
            cost.warehouse_ceiling(ctx.con),
        )
    finally:
        guard.plan_of = real
    true(not verdict.allowed, "an unreadable plan is refused")
    eq(verdict.stage, "cost", "stage")
    eq(verdict.reason, "no_estimate", "reason")


def check_the_pipeline_cannot_reach_the_cost_layer_around_the_door():
    """`ot-026`, applied a second time.

    A ceiling the caller invokes is a ceiling the caller can forget. The day 4 answer was
    to compose the layers inside `agent.guard` and let nothing else touch them, and the
    day 5 layer went in the same place. This pins that the pipeline still asks for one
    thing and gets all three.
    """
    import os

    from agent import pipeline
    from tests import structural

    agent_dir = os.path.dirname(os.path.abspath(pipeline.__file__))
    names = structural.called_attribute_names(os.path.join(agent_dir, "pipeline.py"))
    true("guard.execute" in names, "pipeline calls guard.execute")
    for reached_past in ("cost.judge", "cost.read_plan", "guard.plan_of", "guard.approve"):
        true(reached_past not in names, "pipeline does not call %s" % reached_past)


def check_the_gate_still_runs_before_the_estimate(ctx):
    """A stacked statement must never reach `EXPLAIN`, which would run the first half."""
    verdict = guard.approve(
        ctx.con,
        _tables(ctx),
        "SELECT 1 AS ok; SELECT count(*) FROM retail.dim_store",
        cost.warehouse_ceiling(ctx.con),
    )
    eq(verdict.stage, "gate", "stage")
    eq(verdict.reason, "multiple_statements", "reason")
    true(verdict.judgement is None, "cost never ran")
    true(not hasattr(role, "explain"), "and role has no plan path of its own")
