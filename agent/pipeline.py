"""One question in, one attempt out, with every step recorded.

This is the spine days 4 to 6 hang off. Day 4 put static validation behind `agent.guard`
rather than adding a step here, so the ordering lives next to the thing it protects.
Day 5 adds a cost estimate after approval and before execution. Day 6 loops this whole
thing when a step fails. The steps are recorded in a list rather than logged, because the
trace viewer is a deliverable and reconstructing a trace from log lines is work nobody
enjoys.

There is deliberately no retry here yet. Day 6 owns that, and writing an empty retry loop
today so it looks finished is the padding this program's audit asks about.
"""

from dataclasses import dataclass, field

from agent import generate, guard, prompt as prompt_mod


@dataclass
class Attempt:
    question: str
    steps: list = field(default_factory=list)
    sql: str = ""
    rows: tuple = ()
    outcome: str = ""
    detail: str = ""
    verdict: object = None

    def step(self, name, ok, detail=""):
        self.steps.append({"step": name, "ok": ok, "detail": detail})

    def as_dict(self):
        out = {
            "question": self.question,
            "outcome": self.outcome,
            "detail": self.detail,
            "sql": self.sql,
            "row_count": len(self.rows),
            "steps": list(self.steps),
        }
        if self.verdict is not None:
            out["verdict"] = self.verdict.as_dict()
        return out


def answer(con, question, tables, generator, chosen=None):
    """Build a prompt then generate then gate then execute. Never raises for a bad query.

    Outcomes are a closed set and every caller downstream switches on them, so they are
    listed here rather than left for a reader to collect from the branches.

        answered        the query was approved and ran
        cannot_answer   the generator declined
        refused         the gate or the validator rejected it, `detail` says which rule
        failed          the SQL was approved and the database rejected it anyway

    A refusal and a database error are kept apart because day 6 has to send different
    things back to the model, and because collapsing them would hide the case where both
    layers approve something that cannot run. That case is the point of the `failed`
    outcome and it is not hypothetical. Static validation checks that names exist and
    says nothing about types.
    """
    attempt = Attempt(question=question)

    built = prompt_mod.build(question, tables, chosen)
    attempt.step("prompt", True, "%d chars" % built.sizes()["total"])

    try:
        raw = generator.generate(built.text)
    except generate.GeneratorError as exc:
        attempt.outcome, attempt.detail = "failed", str(exc)
        attempt.step("generate", False, str(exc))
        return attempt
    attempt.step("generate", True, generator.name)

    try:
        kind, sql = generate.parse(raw)
    except generate.GeneratorError as exc:
        attempt.outcome, attempt.detail = "failed", str(exc)
        attempt.step("parse", False, str(exc))
        return attempt

    if kind == "cannot_answer":
        attempt.outcome = "cannot_answer"
        attempt.step("parse", True, "generator declined")
        return attempt

    attempt.sql = sql
    attempt.step("parse", True, "%d chars of SQL" % len(sql))

    # One call, so the query is approved once rather than once for the trace and again
    # for the run. The verdict carries both layers, which is what the steps below read.
    result = guard.execute(con, tables, sql)
    verdict = result.verdict
    attempt.verdict = verdict

    attempt.step("gate", verdict.stage != "gate", verdict.decision.reason)
    if verdict.stage != "gate":
        codes = verdict.report.codes() if verdict.report else ()
        attempt.step("validate", verdict.allowed, ",".join(codes) or "clean")
    if not verdict.allowed:
        attempt.outcome, attempt.detail = "refused", verdict.reason
        return attempt

    if not result.ran:
        attempt.outcome, attempt.detail = "failed", result.error
        attempt.step("execute", False, result.error)
        return attempt

    attempt.rows = tuple(result.rows)

    attempt.step("execute", True, "%d rows" % len(attempt.rows))
    attempt.outcome = "answered"
    return attempt
