"""The one door model-produced SQL goes through to reach the database.

The gate left two ways to run a query. `role.run` gated on the parser and executed, and
`pipeline.answer` gated on the parser and then called `con.execute` itself. Both were
correct at the time. Neither knew about the catalog, so when I added static
validation there would have been two places to remember to add it, and a rule a caller
has to remember to invoke is a rule that is
optional. So `role.run` is gone and this is the only path.

Order matters and it is not arbitrary:

    1. role.inspect    is this one read at all
    2. validate.check  does it refer to things that exist, and only to those things
    3. cost.judge      what will it make the engine do
    4. execute

The parser gate runs first because validation has to walk a parse tree, and asking for
the tree of a string that is not a query is how a validator ends up reporting a
`BinderException` as a schema problem. It also means a stacked exfiltration is refused
before this module has looked at a single column name.

The cost layer put the cost estimate last, and that position was measured rather than assumed.
**`EXPLAIN` is not a dry run.** It binds the query, and binding a table function opens
the thing the function points at. `EXPLAIN (FORMAT JSON) SELECT * FROM
read_csv('/tmp/probe.csv')` came back with `Projections: ["a", "b"]`, which are the
column names out of the file, so the file was read. Point it at a path that does not
exist and it raises `IOException: No files found`. So a cost layer placed first, on the
reasonable sounding argument that the cheap check should run before the expensive one,
would hand an attacker the exact filesystem read that `agent.validate` exists to remove.
Cost estimation runs on a query two layers have already approved, or it does not run.

`tests/test_guard.py` pins that model SQL cannot reach the database any other way. It
walks `agent/` with `ast` and requires every `.execute()` call outside this module to
pass a string literal. A literal is not model output. That is a check on the shape of
the code rather than on its behaviour, which is the only kind that catches the caller
who forgets in six weeks.
"""

import json
from dataclasses import dataclass

from agent import cost, role, validate


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    stage: str          # "gate", "validate", "cost" or "approved"
    reason: str
    detail: str = ""
    decision: object = None
    report: object = None
    judgement: object = None

    def as_dict(self):
        out = {
            "allowed": self.allowed,
            "stage": self.stage,
            "reason": self.reason,
            "detail": self.detail,
        }
        if self.decision is not None:
            out["gate"] = self.decision.as_dict()
        if self.report is not None:
            out["validation"] = self.report.as_dict()
        if self.judgement is not None:
            out["cost"] = self.judgement.as_dict()
        return out


def plan_of(con, sql, dialect=None):
    """Ask the engine for the plan of `sql`. The second call that touches model text.

    This is here and not in `agent.cost` because it is an `.execute()` handed something
    that is not a literal, and the whole rule of this module is that those live behind
    one door. `tests/structural.py` enforces that by reading the code, and the fixture it
    reads was written with a `plan()` helper in it, before this function
    existed. The convention predicted its own first real user.

    The prefix comes from the dialect record rather than from a string here, so the
    Snowflake form stays visible in `warehouse/adapter.py` even though nothing in this
    repo has run against Snowflake.
    """
    if dialect is None:
        from warehouse import adapter

        dialect = adapter.duckdb()
    statement = "EXPLAIN (FORMAT JSON) %s" % sql.rstrip().rstrip(";")
    if dialect.name != "duckdb":
        statement = dialect.explain(sql)
    return json.loads(con.execute(statement).fetchall()[0][1])


GATE = "gate"
VALIDATE = "validate"
COST = "cost"
LAYERS = (GATE, VALIDATE, COST)


def approve(con, tables, sql, ceiling=None, layers=LAYERS):
    """Run every layer and say which one refused, without running the query itself.

    `ceiling` of None means no cost check, which is what the reports that measure the
    earlier layers on their own want. It is not the default anywhere real. `pipeline`
    reads one off the warehouse and passes it.

    `layers` exists for exactly one caller, `evals.scorecard.ablate`, which measures what
    each layer contributes by taking it away. It is not a feature and it is not a way to
    turn the guard down. An empty set raises rather than approving, because a door with
    no locks on it is a bug here and never a configuration. `tests/test_guard.py` fails
    if anything in `agent/` ever passes this argument.
    """
    layers = tuple(layers)
    unknown = [name for name in layers if name not in LAYERS]
    if unknown:
        raise ValueError("unknown layer(s): %s" % ", ".join(sorted(unknown)))
    if not layers:
        raise ValueError(
            "approve with no layers is a bug, not an open door. Call the connection "
            "directly if that is really what you meant."
        )

    decision = None
    if GATE in layers:
        decision = role.inspect(con, sql)
        if not decision.allowed:
            return Verdict(False, "gate", decision.reason, decision.detail, decision, None)

    if VALIDATE not in layers:
        return _after_validation(con, sql, ceiling, layers, decision, None)

    report = validate.check(con, tables, sql)
    if not report.ok:
        first = report.findings[0]
        return Verdict(
            False,
            "validate",
            first.code,
            "; ".join(str(f) for f in report.findings),
            decision,
            report,
        )

    return _after_validation(con, sql, ceiling, layers, decision, report)


def _after_validation(con, sql, ceiling, layers, decision, report):
    """The cost layer and the approval, shared by both routes into it.

    This is a helper rather than a second door. It runs no query the caller did not
    already reach through `approve`, and `plan_of` is still the only `.execute()` of
    model text in this module.
    """
    if ceiling is None or COST not in layers:
        return Verdict(True, "approved", "single_read_on_known_objects", "", decision, report)

    try:
        estimate = cost.read_plan(plan_of(con, sql))
    except cost.NothingToEstimate as exc:
        # A plan nothing could be read out of is refused rather than waved through. It
        # should be unreachable, because validation refuses a query that reads no table
        # in the warehouse, so if this ever fires the interesting part is which of the
        # two layers was wrong.
        #
        # A plan the engine refuses to PRODUCE is a different case and it is deliberately
        # not caught here. `EXPLAIN` binds, so it raises on a write and on a query naming
        # a relation that does not exist, and both of those are refused by a layer above
        # before this line runs. The ablation depends on that exception escaping.
        # Swallowing it would make a cost-only arm look like it refuses a DELETE, which
        # it does not. What it does is fail to plan one. See `docs/adr-0011`.
        return Verdict(
            False, "cost", "no_estimate", str(exc), decision, report,
            cost.Judgement(False, "no_estimate", str(exc), None, ceiling),
        )

    judgement = cost.judge(estimate, ceiling)
    if not judgement.ok:
        return Verdict(
            False, "cost", judgement.code, judgement.detail, decision, report, judgement
        )

    return Verdict(
        True, "approved", "single_read_on_known_objects", "", decision, report, judgement
    )


@dataclass(frozen=True)
class Result:
    verdict: Verdict
    rows: object = None      # None when refused or when execution failed
    error: str = ""

    @property
    def ran(self):
        return self.rows is not None


def execute(con, tables, sql, ceiling=None):
    """Approve, then run if approved. Returns a `Result` and never raises.

    `rows` is None both when the verdict refused and when the database rejected the
    query, and `verdict.allowed` is what tells those apart. A caller that ignores all of
    this and iterates `rows` gets a TypeError immediately rather than an empty list that
    looks like a query returning nothing.

    This approves once. The first draft had the pipeline call `approve` for its trace and
    then call this, which approved a second time and parsed the same query four times.
    Approval is already about half the cost of running these queries, measured over the
    answer key, so paying it twice for a trace line was not a rounding error.
    """
    try:
        verdict = approve(con, tables, sql, ceiling)
    except Exception as exc:                                # noqa: BLE001
        # `approve` can raise, and a later review found a query that does it. `EXPLAIN`
        # binds, so a qualifier that no relation defines raises a `BinderException` out
        # of the cost layer. Validation catches that when the statement has no CTE and no
        # subquery, and it cannot when there is one, because resolving a name through a
        # derived table is the binder's job.
        #
        # The catch is here rather than inside `approve` on purpose. This function is the
        # one documented never to raise. `approve` is also what the ablation calls,
        # and an ablation that never saw an exception would report a cost-only guard as
        # refusing a `DELETE` when what it really does is fail to plan one.
        return Result(
            Verdict(False, "cost", "no_estimate", str(exc).splitlines()[0]),
            None,
            str(exc).splitlines()[0],
        )
    if not verdict.allowed:
        return Result(verdict)
    try:
        return Result(verdict, con.execute(sql).fetchall())
    except Exception as exc:
        return Result(verdict, None, str(exc).splitlines()[0])
