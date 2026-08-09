"""One question in, one attempt out, with every step recorded.

This is the spine days 4 to 6 hang off. Day 4 adds static validation between the parse
and the gate. Day 5 adds a cost estimate after the gate and before execution. Day 6 loops
this whole thing when a step fails. The steps are recorded in a list rather than logged,
because the trace viewer is a deliverable and reconstructing a trace from log lines is
work nobody enjoys.

There is deliberately no retry here yet. Day 6 owns that, and writing an empty retry loop
today so it looks finished is the padding this program's audit asks about.
"""

from dataclasses import dataclass, field

from agent import generate, prompt as prompt_mod, role


@dataclass
class Attempt:
    question: str
    steps: list = field(default_factory=list)
    sql: str = ""
    rows: tuple = ()
    outcome: str = ""
    detail: str = ""

    def step(self, name, ok, detail=""):
        self.steps.append({"step": name, "ok": ok, "detail": detail})

    def as_dict(self):
        return {
            "question": self.question,
            "outcome": self.outcome,
            "detail": self.detail,
            "sql": self.sql,
            "row_count": len(self.rows),
            "steps": list(self.steps),
        }


def answer(con, question, tables, generator, chosen=None):
    """Build a prompt then generate then gate then execute. Never raises for a bad query.

    Outcomes are a closed set and every caller downstream switches on them, so they are
    listed here rather than left for a reader to collect from the branches.

        answered        the query passed the gate and ran
        cannot_answer   the generator declined
        refused         the gate rejected the SQL, `detail` says which rule
        failed          the SQL passed the gate and the database rejected it

    A gate refusal and a database error are kept apart because day 6 has to send
    different things back to the model, and because collapsing them would hide the case
    where the gate approves something that cannot run.
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

    decision = role.inspect(con, sql)
    attempt.step("gate", decision.allowed, decision.reason)
    if not decision.allowed:
        attempt.outcome, attempt.detail = "refused", decision.reason
        return attempt

    try:
        attempt.rows = tuple(con.execute(sql).fetchall())
    except Exception as exc:
        attempt.outcome, attempt.detail = "failed", str(exc).splitlines()[0]
        attempt.step("execute", False, attempt.detail)
        return attempt

    attempt.step("execute", True, "%d rows" % len(attempt.rows))
    attempt.outcome = "answered"
    return attempt
