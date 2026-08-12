"""One question in, one attempt out, with every step recorded. Then `solve` loops it.

This is the spine days 4 to 6 hang off. Day 4 put static validation behind `agent.guard`
rather than adding a step here, so the ordering lives next to the thing it protects. Day
5 did the same with the cost ceiling and for the same reason, so what this file gained is
a ceiling to pass and a step to record rather than any logic. The steps are recorded in a
list rather than logged, because the trace is a deliverable and reconstructing one from
log lines is work nobody enjoys.

Day 6 added `solve`, which calls `answer` again when a correction is worth sending. It
calls `answer` and nothing else. It does not reach for `guard.approve`, `validate.check`
or `cost.judge`, because a loop that assembles the layers itself is a second door into
the database and `ot-026` is the thread that says a rule a caller has to remember is a
rule that is optional. Every attempt in a trace went through the same one door as a
single attempt does.
"""

from dataclasses import dataclass, field

from agent import correct, generate, guard, prompt as prompt_mod, trace as trace_mod


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


def answer(con, question, tables, generator, chosen=None, ceiling=None, correction=""):
    """Build a prompt then generate then gate then execute. Never raises for a bad query.

    Outcomes are a closed set and every caller downstream switches on them, so they are
    listed here rather than left for a reader to collect from the branches.

        answered        the query was approved and ran
        cannot_answer   the generator declined
        refused         a guard layer rejected it, `detail` says which rule
        failed          the SQL was approved and the database rejected it anyway

    A refusal and a database error are kept apart because day 6 has to send different
    things back to the model, and because collapsing them would hide the case where both
    layers approve something that cannot run. That case is the point of the `failed`
    outcome and it is not hypothetical. Static validation checks that names exist and
    says nothing about types.
    """
    attempt = Attempt(question=question)

    built = prompt_mod.build(question, tables, chosen, correction=correction)
    sizes = built.sizes()
    detail = "%d chars" % sizes["total"]
    if sizes["correction"]:
        detail += ", %d of correction" % sizes["correction"]
    attempt.step("prompt", True, detail)

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
    result = guard.execute(con, tables, sql, ceiling)
    verdict = result.verdict
    attempt.verdict = verdict

    attempt.step("gate", verdict.stage != "gate", verdict.decision.reason)
    if verdict.stage != "gate":
        codes = verdict.report.codes() if verdict.report else ()
        attempt.step("validate", verdict.stage != "validate", ",".join(codes) or "clean")
    if verdict.judgement is not None:
        judgement = verdict.judgement
        detail = judgement.detail or "peak %d rows under %d" % (
            judgement.estimate.peak_rows, judgement.ceiling,
        )
        attempt.step("cost", judgement.ok, detail)
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


def solve(con, question, tables, generator, chosen=None, ceiling=None, max_retries=2):
    """Attempt, correct, attempt again. At most `max_retries` corrections.

    Returns a `trace.Trace` holding every attempt and every correction, including the
    corrections that were not sent. A trace that only recorded what was sent could not
    answer the question a reader actually has, which is why the loop stopped.

    There are four ways this ends and they are kept apart on purpose.

        resolved              an attempt was answered
        stopped_unretryable   the refusal is one `agent.correct` does not coach
        stopped_repeated      the generator produced SQL it had already produced
        stopped_at_cap        the budget ran out with the query still refused

    `stopped_repeated` is the one that earns its place. The cap bounds the damage. It
    does not stop a generator that ignores the correction, and a generator that ignores
    the correction returns the same string, which is refused for the same reason by the
    same layer. Comparing the SQL costs a set lookup and ends those traces one attempt
    early. It also makes the useless retry visible in the record instead of hiding it
    inside a count that reads as if the budget was spent on something.
    """
    if max_retries < 0:
        raise ValueError("max_retries must be zero or more, got %r" % max_retries)

    trace = trace_mod.Trace(question=question, max_retries=max_retries)
    correction_text = ""
    seen_sql = set()

    while True:
        attempt = answer(con, question, tables, generator, chosen, ceiling, correction_text)

        if attempt.outcome == "answered":
            trace.add(attempt)
            trace.ending = trace_mod.RESOLVED
            return trace

        # Compared before the correction is built, so a repeat is reported as a repeat
        # rather than as whatever the layers said about it for the second time.
        normalised = _normalise(attempt.sql)
        repeated = bool(normalised) and normalised in seen_sql
        seen_sql.add(normalised)

        correction = correct.correction_for(attempt)
        trace.add(attempt, correction)

        if correction.action == correct.STOP:
            trace.ending = trace_mod.STOPPED_UNRETRYABLE
            return trace
        if repeated:
            trace.ending = trace_mod.STOPPED_REPEATED
            return trace
        if trace.retries >= max_retries:
            trace.ending = trace_mod.STOPPED_AT_CAP
            return trace

        correction_text = correct.render(correction)


def _normalise(sql):
    """Whitespace and case folded, so a reindented repeat still reads as a repeat.

    Deliberately not a parse. Two queries that differ only in whitespace are the same
    attempt for this purpose, and two that differ anywhere else get another turn even if
    a parser would call them equivalent. Being generous here would end a trace that was
    genuinely making progress.
    """
    return " ".join((sql or "").split()).lower().rstrip(";")
