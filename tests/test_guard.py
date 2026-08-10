"""Checks on the composed guard, and on the shape of the code around it.

The last check in this file is the one that matters most and it does not run any SQL.
`ot-026` is an open thread from an earlier project about a rule that a caller has to
remember to invoke. The answer here is that there is one door, and the way to keep it
one door is to fail the suite when a second appears.
"""

import ast
import os

from agent import guard, role, validate
from tests.harness import eq, true
from warehouse import catalog

AGENT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent"
)


def _tables(ctx):
    return catalog.read(ctx.con)


def check_the_gate_refuses_before_validation_looks(ctx):
    """Order is load bearing. A write must not reach a module that expects a parse tree."""
    v = guard.approve(ctx.con, _tables(ctx), "DROP TABLE retail.fct_return")
    eq(v.stage, "gate", "stage")
    eq(v.reason, "not_a_read", "reason")
    true(v.report is None, "validation never ran")


def check_validation_refuses_what_the_gate_allowed(ctx):
    v = guard.approve(ctx.con, _tables(ctx), "SELECT * FROM read_csv('/etc/hostname')")
    eq(v.stage, "validate", "stage")
    eq(v.reason, "table_function", "reason")
    true(v.decision.allowed, "the gate had approved it")


def check_a_good_query_is_approved_by_both(ctx):
    v = guard.approve(ctx.con, _tables(ctx), "SELECT order_id FROM retail.fct_order_header")
    true(v.allowed, "allowed")
    eq(v.stage, "approved", "stage")
    true(v.report.ok, "report clean")


def check_execute_returns_rows_and_a_verdict(ctx):
    r = guard.execute(ctx.con, _tables(ctx), "SELECT COUNT(*) FROM retail.dim_customer")
    true(r.ran, "ran")
    eq(len(r.rows), 1, "one row")
    true(r.rows[0][0] > 0, "a real count")
    true(r.verdict.allowed, "verdict")
    eq(r.error, "", "no error")


def check_execute_does_not_run_a_validation_refusal(ctx):
    r = guard.execute(ctx.con, _tables(ctx), "SELECT * FROM glob('/etc/*')")
    true(not r.verdict.allowed, "refused")
    eq(r.verdict.reason, "table_function", "reason")
    # None rather than an empty list, so a caller who ignores the verdict breaks loudly.
    true(r.rows is None, "nothing came back")
    true(not r.ran, "ran is false")


def check_execute_does_not_run_a_gate_refusal(ctx):
    r = guard.execute(ctx.con, _tables(ctx), "SELECT 1; SELECT 2")
    eq(r.verdict.reason, "multiple_statements", "reason")
    eq(r.verdict.stage, "gate", "stage")
    true(r.rows is None, "nothing came back")


def check_an_approved_query_the_database_rejects_is_not_a_refusal(ctx):
    """`ran` is false and `verdict.allowed` is true. Those are different facts."""
    r = guard.execute(
        ctx.con,
        _tables(ctx),
        "SELECT CAST(customer_email AS INTEGER) AS n FROM retail.dim_customer",
    )
    true(r.verdict.allowed, "both layers approved it")
    true(not r.ran, "it did not run")
    true("Conversion Error" in r.error, "the error survives: %s" % r.error)


def check_the_verdict_carries_both_layers_for_the_trace(ctx):
    import json

    v = guard.approve(ctx.con, _tables(ctx), "SELECT order_id FROM retail.fct_order_header")
    payload = json.loads(json.dumps(v.as_dict()))
    true("gate" in payload, "gate decision present")
    true("validation" in payload, "validation report present")
    eq(payload["stage"], "approved", "stage")


def check_role_no_longer_offers_a_second_door(ctx):
    """`role.run` gated on the parser and knew nothing about the catalog."""
    true(not hasattr(role, "run"), "role.run is gone")


def check_model_sql_can_only_reach_the_database_through_guard():
    """Every `.execute()` outside guard.py must be given a string literal.

    A literal cannot be model output. So this is a structural statement that generated
    SQL has exactly one path to the connection, and it fails the moment someone adds a
    second one. Behaviour tests cannot catch that, because the new path would have its
    own passing tests.
    """
    offenders = []
    for name in sorted(os.listdir(AGENT_DIR)):
        if not name.endswith(".py") or name == "guard.py":
            continue
        path = os.path.join(AGENT_DIR, name)
        with open(path) as fh:
            tree = ast.parse(fh.read(), filename=name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "execute":
                continue
            # `guard.execute(...)` is the door itself, not a way round it.
            if isinstance(func.value, ast.Name) and func.value.id == "guard":
                continue
            first = node.args[0] if node.args else None
            if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                offenders.append("%s:%d" % (name, node.lineno))
    eq(offenders, [], "non literal .execute() calls outside guard.py")


def check_the_validator_is_reachable_from_the_pipeline():
    """A guard nothing calls is decoration. Pinned by import, not by reading the file."""
    from agent import pipeline

    src = os.path.join(AGENT_DIR, "pipeline.py")
    with open(src) as fh:
        tree = ast.parse(fh.read())
    names = {
        n.func.value.id + "." + n.func.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
    }
    true("guard.execute" in names, "pipeline calls guard.execute")
    true(pipeline.guard is guard, "and it is this guard")
    # And it does not reach past the door to either layer on its own.
    true("role.inspect" not in names, "pipeline does not call role.inspect directly")
    true("validate.check" not in names, "pipeline does not call validate.check directly")


def check_validate_is_not_importable_as_an_execution_path():
    """`validate` reports. It must never be the thing that runs the query."""
    true(not hasattr(validate, "execute"), "validate has no execute")
    true(not hasattr(validate, "run"), "validate has no run")
