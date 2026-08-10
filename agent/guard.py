"""The one door model-produced SQL goes through to reach the database.

Day 3 left two ways to run a query. `role.run` gated on the parser and executed, and
`pipeline.answer` gated on the parser and then called `con.execute` itself. Both were
correct on the day. Neither knew about the catalog, so when day 4 added static
validation there would have been two places to remember to add it, and `ot-026` is the
open thread that says a rule a caller has to remember to invoke is a rule that is
optional. So `role.run` is gone and this is the only path.

Order matters and it is not arbitrary:

    1. role.inspect    is this one read at all
    2. validate.check  does it refer to things that exist, and only to those things
    3. execute

The parser gate runs first because validation has to walk a parse tree, and asking for
the tree of a string that is not a query is how a validator ends up reporting a
`BinderException` as a schema problem. It also means a stacked exfiltration is refused
before this module has looked at a single column name.

`tests/test_guard.py` pins that model SQL cannot reach the database any other way. It
walks `agent/` with `ast` and requires every `.execute()` call outside this module to
pass a string literal. A literal is not model output. That is a check on the shape of
the code rather than on its behaviour, which is the only kind that catches the caller
who forgets in six weeks.
"""

from dataclasses import dataclass

from agent import role, validate


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    stage: str          # "gate", "validate" or "approved"
    reason: str
    detail: str = ""
    decision: object = None
    report: object = None

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
        return out


def approve(con, tables, sql):
    """Run both layers and say which one refused, without running anything."""
    decision = role.inspect(con, sql)
    if not decision.allowed:
        return Verdict(False, "gate", decision.reason, decision.detail, decision, None)

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

    return Verdict(True, "approved", "single_read_on_known_objects", "", decision, report)


@dataclass(frozen=True)
class Result:
    verdict: Verdict
    rows: object = None      # None when refused or when execution failed
    error: str = ""

    @property
    def ran(self):
        return self.rows is not None


def execute(con, tables, sql):
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
    verdict = approve(con, tables, sql)
    if not verdict.allowed:
        return Result(verdict)
    try:
        return Result(verdict, con.execute(sql).fetchall())
    except Exception as exc:
        return Result(verdict, None, str(exc).splitlines()[0])
