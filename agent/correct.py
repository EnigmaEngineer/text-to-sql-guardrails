"""Turn a refusal into something worth sending back, or say there is nothing to send.

The loop itself is small. The part worth building carefully is deciding which failures
deserve another attempt. A retry costs a whole pass over the prompt and all three guard
layers.

Two independent questions get asked about every refusal, and keeping them apart is the
whole point of this module.

**Is the refusal novel.** Does it carry a fact the prompt did not already contain. The
schema goes into every prompt in full, so a query naming a column that is not in the
catalog was checkable by the model before it answered. A parser error and a row estimate
were not. `novel` records that and nothing else. It is not a policy.

**Should the agent retry.** A separate call, and it is not the same split. A refusal can
be worth pointing at even when it tells the model nothing new, because "you invented
this column" is a pointer at the mistake rather than information about the world, and a
pointer is usually enough. What is never retried is a refusal of intent. A query that
writes, a query that chains statements, and a query that reads a host file are not slips
to coach. Sending a correction there hands whatever produced the query another turn at
the same target, which is help nobody wanted to give.

So `stop` is a security position and not an efficiency one. It costs the agent a small
number of genuine recoveries in exchange for never iterating on an attack.

The code list is NOT written from memory. `tests/test_correct.py` walks every module in
`agent/` with `ast`. It pulls out each refusal code built from a string literal and fails
when one has no entry here. On 08-11 a list of plan operators was written from memory and
both halves of it were wrong. This is that lesson applied before the same mistake could be
made twice.
"""

from dataclasses import dataclass

REVISE = "revise"
STOP = "stop"


@dataclass(frozen=True)
class Strategy:
    action: str
    novel: bool
    instruction: str
    why: str = ""


@dataclass(frozen=True)
class Correction:
    code: str
    action: str
    novel: bool
    text: str

    @property
    def retryable(self):
        return self.action == REVISE

    def as_dict(self):
        return {
            "code": self.code,
            "action": self.action,
            "novel": self.novel,
            "text": self.text,
        }


# Keyed by the refusal code exactly as the layer that produced it wrote it. `novel` is a
# claim about the prompt, so it is asserted per code and checked in the tests against
# `agent.prompt.RULES` and against whether the schema alone answers it.
STRATEGY = {
    # --- agent.role, the parser gate -------------------------------------------------
    "empty": Strategy(
        REVISE, False,
        "Your reply contained no SQL statement. Reply with exactly one SELECT.",
    ),
    "not_a_read": Strategy(
        STOP, False,
        "",
        "a write was asked for against a read-only agent. Rule 2 of the prompt said "
        "SELECT only, so this is intent rather than a slip and it is not coached.",
    ),
    "unparseable": Strategy(
        REVISE, True,
        "The database could not parse your query. The parser said: {detail}",
        "the parser error is the one thing here the model could not have worked out "
        "from the prompt.",
    ),
    "multiple_statements": Strategy(
        STOP, False,
        "",
        "chained statements are the exfiltration shape the gate measured. Not coached.",
    ),
    # --- agent.validate, static validation --------------------------------------------
    "table_function": Strategy(
        STOP, False,
        "",
        "a table function pointed outside the catalog reads the host filesystem. "
        "Coaching it is handing the next attempt a hint. Not coached.",
    ),
    "unknown_table": Strategy(
        REVISE, False,
        "{detail}. Use only the tables in the schema above.",
    ),
    "unknown_column": Strategy(
        REVISE, False,
        "{detail}. Check the column against the schema above before using it.",
    ),
    "no_relation": Strategy(
        REVISE, False,
        "Your query reads no table in the warehouse. Answer from the schema above, or "
        "reply CANNOT_ANSWER.",
    ),
    "cross_join": Strategy(
        REVISE, False,
        "{detail}. Join the tables on their keys instead.",
    ),
    "implicit_join": Strategy(
        REVISE, False,
        "{detail}. Write the join condition out.",
    ),
    "unrelated_join": Strategy(
        REVISE, False,
        "{detail}. Give the join a condition relating a column of one side to a column "
        "of the other.",
    ),
    # --- agent.cost, the ceiling -------------------------------------------------------
    "over_ceiling": Strategy(
        REVISE, True,
        "This query is too expensive to run. {detail}. Narrow it with a filter, an "
        "aggregate or a smaller table.",
        "the row estimate comes from the planner and is not derivable from the prompt.",
    ),
    "unscored_operator": Strategy(
        REVISE, True,
        "The planner cannot estimate the cost of this query. {detail}. Rewrite the join "
        "so both sides are related by an equality on their keys.",
        "which operator the planner chose is a fact about the engine.",
    ),
    "no_estimate": Strategy(
        REVISE, True,
        "The planner produced no usable estimate for this query. {detail}",
        "same as unscored_operator. It is a property of the plan document.",
    ),
}

# Outcomes that are not refusals but still end an attempt. Kept beside the codes because
# `correction_for` has to answer for all of them and a caller should not have to know
# which of the two tables an outcome lives in.
OUTCOME_STRATEGY = {
    "cannot_answer": Strategy(
        STOP, False,
        "",
        "the generator declined. Nothing about the question or the schema changed "
        "between attempts, so asking again gets the same answer for the same reason.",
    ),
    "failed": Strategy(
        REVISE, True,
        "Your query was accepted by the checks and the database rejected it: {detail}",
        "the runtime error is produced by the engine on real data. Static validation "
        "checks that names exist and has no opinion about types.",
    ),
}

NOVEL_CODES = tuple(sorted(c for c, s in STRATEGY.items() if s.novel))


class NoStrategy(KeyError):
    """A refusal code with no entry. Loud on purpose, see the module docstring."""


def strategy_for(attempt):
    """Which strategy applies. Raises rather than guessing at an unknown code."""
    if attempt.outcome == "answered":
        return None
    if attempt.outcome in ("cannot_answer",):
        return OUTCOME_STRATEGY["cannot_answer"]
    if attempt.outcome == "failed":
        # A generator or parse failure is not a database rejection and has no SQL behind
        # it. It reuses the same strategy because both hand back an engine message the
        # model could not have predicted.
        return OUTCOME_STRATEGY["failed"]
    if attempt.outcome != "refused":
        raise NoStrategy("unknown outcome %r" % attempt.outcome)

    code = attempt.verdict.reason if attempt.verdict is not None else attempt.detail
    if code not in STRATEGY:
        raise NoStrategy(
            "refusal code %r has no correction strategy. Add one to agent.correct "
            "rather than letting the loop decide by default." % code
        )
    return STRATEGY[code]


def correction_for(attempt):
    """The correction to send back, or one carrying `action == STOP`.

    The detail comes off the verdict rather than off the attempt, because a verdict
    detail names the offending object and an attempt detail is the code. A model told
    "unknown_column" learns less than one told which column.
    """
    strategy = strategy_for(attempt)
    if strategy is None:
        return None

    code = attempt.detail
    if attempt.outcome == "refused" and attempt.verdict is not None:
        code = attempt.verdict.reason

    detail = ""
    if attempt.verdict is not None and attempt.outcome == "refused":
        detail = attempt.verdict.detail or ""
    elif attempt.outcome == "failed":
        detail = attempt.detail or ""

    text = ""
    if strategy.action == REVISE:
        text = strategy.instruction.format(detail=detail.rstrip("."))
    return Correction(code=code, action=strategy.action, novel=strategy.novel, text=text)


def render(correction):
    """The block that goes into the next prompt.

    Placed before the question rather than after it, so `generate.question_of` still
    finds the question as the last section. That is not a detail. The scripted generator
    keys on the question, and a correction appended after it would have silently made
    every retry unscriptable.
    """
    if correction is None or not correction.text:
        return ""
    return (
        "Your previous attempt was rejected before it ran. Correct it and reply with "
        "one SELECT.\n- " + correction.text
    )
