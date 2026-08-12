"""Checks on the self correction loop and on the trace it produces.

Each of the four endings gets a case. An ending with no test is an ending that can be
produced by accident, which is the same rule the outcome tests in `test_pipeline` follow.
"""

import json

from agent import correct, generate, pipeline, trace as trace_mod
from tests.harness import eq, raises, true
from warehouse import catalog

GOOD = "SELECT count(*) AS n FROM retail.dim_customer"
BAD_COLUMN = "SELECT favourite_colour FROM retail.dim_customer"
BAD_TABLE = "SELECT * FROM retail.fct_orders"
BAD_SYNTAX = "SELECT FROM WHERE"


def solve_with(ctx, question, answers, max_retries=2):
    tables = catalog.read(ctx.con)
    g = generate.SequenceGenerator({question: answers})
    return pipeline.solve(ctx.con, question, tables, g, max_retries=max_retries)


def check_a_first_attempt_that_works_is_not_retried(ctx):
    t = solve_with(ctx, "how many customers", [GOOD])
    eq(t.ending, trace_mod.RESOLVED, "ending")
    eq(t.retries, 0, "no retries")
    eq(len(t.attempts), 1, "one attempt")
    # Parallel to `attempts`, so an answered attempt holds None rather than being
    # missing. A shorter list would make every reader index the two against each other.
    eq(t.corrections, [None], "no correction recorded")


def check_a_correction_can_carry_a_trace_to_an_answer(ctx):
    """The loop working, on real refusals from the real layers.

    The generator does not read the correction. Nothing in this repo does. What this
    pins is that the loop retries, that the second attempt reaches execution, and that
    the trace holds both. It is not evidence that a correction helps a model.
    """
    t = solve_with(ctx, "how many customers", [BAD_COLUMN, GOOD])
    eq(t.ending, trace_mod.RESOLVED, "ending")
    eq(t.retries, 1, "one retry")
    eq(t.outcome, "answered", "final outcome")
    eq(t.attempts[0].detail, "unknown_column", "first refusal")
    eq(t.attempts[1].rows, ((4000,),), "the second attempt really ran")


def check_the_correction_reaches_the_second_prompt(ctx):
    """Otherwise the loop is just three attempts with extra steps."""
    t = solve_with(ctx, "how many customers", [BAD_COLUMN, GOOD])
    first = t.attempts[0].steps[0]["detail"]
    second = t.attempts[1].steps[0]["detail"]
    true("correction" not in first, "first prompt carries no correction: %s" % first)
    true("correction" in second, "second prompt carries one: %s" % second)
    true("favourite_colour" in t.corrections[0].text, "and it names the column")


def check_a_write_is_not_coached_and_ends_the_trace(ctx):
    """One attempt, no retry, and the reason is recorded rather than implied."""
    t = solve_with(ctx, "delete things", ["DELETE FROM retail.dim_customer", GOOD])
    eq(t.ending, trace_mod.STOPPED_UNRETRYABLE, "ending")
    eq(t.retries, 0, "budget untouched")
    eq(t.corrections[0].action, correct.STOP, "not coached")
    eq(t.corrections[0].code, "not_a_read", "code recorded")


def check_a_host_file_read_is_not_coached(ctx):
    t = solve_with(ctx, "read a file", ["SELECT * FROM read_csv('/etc/hostname')", GOOD])
    eq(t.ending, trace_mod.STOPPED_UNRETRYABLE, "ending")
    eq(t.corrections[0].code, "table_function", "refused by validation")
    eq(correct.render(t.corrections[0]), "", "nothing was sent back")


def check_a_repeated_query_ends_the_trace_early(ctx):
    """The cap does not stop a generator that ignores the correction. This does."""
    t = solve_with(ctx, "how many customers", [BAD_COLUMN, BAD_COLUMN, GOOD])
    eq(t.ending, trace_mod.STOPPED_REPEATED, "ending")
    eq(t.retries, 1, "stopped one attempt before the cap")
    eq(len(t.attempts), 2, "two attempts")


def check_whitespace_alone_still_counts_as_a_repeat(ctx):
    reindented = "SELECT   favourite_colour\n  FROM retail.dim_customer"
    t = solve_with(ctx, "how many customers", [BAD_COLUMN, reindented, GOOD])
    eq(t.ending, trace_mod.STOPPED_REPEATED, "reindenting is not progress")


def check_a_different_wrong_query_is_not_a_repeat(ctx):
    """Being generous about what counts as the same query would end a live trace."""
    t = solve_with(ctx, "how many customers", [BAD_COLUMN, BAD_TABLE, GOOD])
    eq(t.ending, trace_mod.RESOLVED, "the third attempt was allowed to happen")
    eq(t.retries, 2, "both retries spent")


def check_the_cap_holds_at_two(ctx):
    t = solve_with(ctx, "how many customers", [BAD_COLUMN, BAD_TABLE, BAD_SYNTAX, GOOD])
    eq(t.ending, trace_mod.STOPPED_AT_CAP, "ending")
    eq(t.retries, 2, "two retries and no more")
    eq(len(t.attempts), 3, "three attempts total")
    eq(t.outcome, "refused", "still refused at the end")


def check_zero_retries_is_a_single_attempt(ctx):
    t = solve_with(ctx, "how many customers", [BAD_COLUMN, GOOD], max_retries=0)
    eq(t.ending, trace_mod.STOPPED_AT_CAP, "ending")
    eq(len(t.attempts), 1, "one attempt")


def check_a_negative_cap_is_refused(ctx):
    tables = catalog.read(ctx.con)
    g = generate.SequenceGenerator({"q": [GOOD]})
    raises(
        lambda: pipeline.solve(ctx.con, "q", tables, g, max_retries=-1),
        "must be zero or more",
        "negative cap",
    )


def check_a_declining_generator_is_not_asked_twice(ctx):
    """Nothing changed between the attempts, so the answer would not change either."""
    tables = catalog.read(ctx.con)
    t = pipeline.solve(ctx.con, "unanswerable", tables, generate.RefusingGenerator())
    eq(t.ending, trace_mod.STOPPED_UNRETRYABLE, "ending")
    eq(len(t.attempts), 1, "asked once")
    eq(t.outcome, "cannot_answer", "outcome")


def check_a_runtime_failure_is_retried(ctx):
    """Both guard layers approved it and the engine rejected it anyway.

    That error is novel by definition. Static validation checks that names exist and has
    no opinion about types, so the conversion error is a fact only the run produced.
    """
    bad_cast = "SELECT CAST(customer_email AS INTEGER) AS n FROM retail.dim_customer"
    t = solve_with(ctx, "bad cast", [bad_cast, GOOD])
    eq(t.ending, trace_mod.RESOLVED, "ending")
    eq(t.attempts[0].outcome, "failed", "first attempt failed at execution")
    true("Conversion Error" in t.corrections[0].text, "the engine error was sent back")
    eq(t.corrections[0].novel, True, "a runtime error is novel")


def check_the_scripted_generator_cannot_exercise_the_loop(ctx):
    """Pinned because it is the reason `SequenceGenerator` exists.

    `ScriptedGenerator` is keyed by question, so it returns the same string on every
    call. A loop tested only with it sends a correction, gets the identical query back,
    and every assertion still passes while nothing reads the correction. Written as a
    check so the next person to reach for the simpler fixture finds out here.
    """
    tables = catalog.read(ctx.con)
    g = generate.ScriptedGenerator({"how many customers": BAD_COLUMN})
    t = pipeline.solve(ctx.con, "how many customers", tables, g)
    eq(t.ending, trace_mod.STOPPED_REPEATED, "the repeat rule catches it")
    eq(len(t.attempts), 2, "and it costs one wasted attempt to find out")


def check_the_sequence_generator_holds_its_last_answer(ctx):
    g = generate.SequenceGenerator({"q": ["a", "b"]})
    prompt_text = "\n\nQuestion: q"
    eq([g.generate(prompt_text) for _ in range(4)], ["a", "b", "b", "b"], "runs on")


def check_an_empty_sequence_is_an_error(ctx):
    g = generate.SequenceGenerator({"q": []})
    raises(lambda: g.generate("\n\nQuestion: q"), "empty sequence", "no answers")


def check_the_trace_serialises(ctx):
    t = solve_with(ctx, "how many customers", [BAD_COLUMN, GOOD])
    payload = json.loads(json.dumps(t.as_dict()))
    eq(payload["ending"], trace_mod.RESOLVED, "round trip")
    eq(len(payload["attempts"]), 2, "both attempts")
    eq(payload["corrections"][0]["code"], "unknown_column", "correction kept")
    eq(payload["corrections"][1], None, "the answered attempt has none")


def check_the_render_shows_which_layer_refused(ctx):
    t = solve_with(ctx, "how many customers", [BAD_COLUMN, GOOD])
    text = trace_mod.render(t)
    true("attempt 1 of 3" in text, "attempts numbered against the budget")
    true("validate FAIL" in text, "the failing layer is marked")
    true("gate     ok" in text, "and the passing one is not")
    true("ending   resolved" in text, "the ending is stated")


def check_the_render_says_when_nothing_was_sent_back(ctx):
    t = solve_with(ctx, "delete things", ["DELETE FROM retail.dim_customer"])
    text = trace_mod.render(t)
    true("not coached (not_a_read)" in text, "the stop is visible: %s" % text)


def check_two_generator_failures_end_at_the_cap_not_as_a_repeat(ctx):
    """A `failed` attempt carries no SQL, and two of those are not the same query.

    Found by a mutant that dropped the emptiness guard from the repeat check. Both
    attempts have `sql == ""`, so without the guard the second reads as a repeat of the
    first and the trace ends `stopped_repeated`. The endings mean different things. One
    says the generator stopped responding to correction and the other says it never
    produced anything to correct.
    """
    tables = catalog.read(ctx.con)
    g = generate.SequenceGenerator({"q": [None, None, GOOD]})
    t = pipeline.solve(ctx.con, "q", tables, g, max_retries=2)
    eq(t.attempts[0].outcome, "failed", "first attempt failed at parse")
    eq(t.attempts[1].outcome, "failed", "second too")
    eq(t.ending, trace_mod.RESOLVED, "the third attempt was still allowed to happen")
    eq(len(t.attempts), 3, "no early stop")


def check_a_long_query_is_clipped_in_the_render(ctx):
    """`_clip` is presentation and it still has a contract worth pinning."""
    long_sql = "SELECT %s FROM retail.dim_customer" % ", ".join(
        ["customer_id"] * 40
    )
    t = solve_with(ctx, "wide", [long_sql, GOOD])
    for line in trace_mod.render(t, width=78).splitlines():
        true(len(line) <= 78, "line overflows the width: %r" % line)
    true("..." in trace_mod.render(t, width=78), "and the clip is visible")


def check_the_render_of_an_empty_trace_does_not_crash():
    t = trace_mod.Trace(question="nothing happened")
    eq(t.final, None, "no final attempt")
    eq(t.retries, 0, "no retries")
    true("nothing happened" in trace_mod.render(t), "still renders")
