# adr-0010: not every refusal is worth a retry, and the trace is text

Day 6. Status: accepted.

## Context

The blueprint asks for a self correction loop capped at two retries, and a trace viewer.
The loop is about forty lines. Everything interesting is in what surrounds it.

There is no model in the environment this repo is built in, which is recorded in
`agent/generate.py` and in the README. So the loop can be exercised and the corrections
cannot be evaluated. Nothing here claims otherwise.

## Decision one: a retry policy per refusal code, derived from the source

`agent/correct.py` holds one strategy per refusal code. Two things get recorded about
each and they are deliberately independent.

`action` is either `revise` or `stop`. `novel` says whether the refusal carries a fact
the prompt did not already contain.

The list is not written by hand. `tests/test_correct.py` walks every module in `agent/`
with `ast`. It pulls out each refusal code built from a string literal and fails when one
has no strategy. It also fails in the other direction, on a strategy for a code nothing
produces. On 08-11 a list of plan operators was written from memory and both halves of it
were wrong, so a list of this kind does not get typed twice.

## Decision two: three refusals are not coached at all

`not_a_read`, `multiple_statements` and `table_function` end the trace with nothing sent
back.

This is a security position and not an efficiency one. A query that writes, a query that
chains statements and a query that reads a host file are not slips. Sending a correction
there gives whatever produced the query another turn at the same target, with a hint about
which layer stopped it. The cost is real. A model that produced a write by accident does
not get the chance to fix it. That trade is worth taking, because the failure it prevents
is worse than the recovery it gives up.

The rendered trace says `not coached` and names the code, so a reader can see the choice
was made rather than that the loop quietly gave up.

## Decision three: stop on a repeat, not only at the cap

The cap bounds the damage. It does not stop a generator that ignores the correction, and
a generator that ignores the correction returns the same string, which is refused for the
same reason by the same layer.

Comparing the normalised SQL against what has already been tried ends those traces one
attempt early. Normalising is whitespace and case only. Two queries that differ anywhere
else get another turn, because being generous about what counts as the same query would
end a trace that was making progress.

This also made the fixture problem visible. `ScriptedGenerator` is keyed by question, so
it returns the same string on every call. A loop tested only with it sends a correction,
gets the identical query back and passes every assertion, having never had its correction
read by anything. `SequenceGenerator` exists because of that and
`check_the_scripted_generator_cannot_exercise_the_loop` pins it.

## Decision four: the trace renders as text

The blueprint lists Streamlit. There is no browser here, so a Streamlit app in this repo
would be a file nobody has ever run, and this program has a standing rule against shipping
components that have never executed.

Text renders in a terminal, in a log and in a Slack message, and a test can assert on it.
`agent/trace.py` is a value plus a renderer, so a different front end is a new function
over the same object rather than a rewrite.

## What this measured

Fourteen refusal codes. Eleven coached, three not. Four novel.

Three of the fourteen are produced by anything other than a test. That is the number worth
sitting with. Most of the correction policy has never met a real input.

A full retry budget costs about 1.5x a clean run rather than 3x, because a refused attempt
is judged and never executed. Measured on the 22 answerable questions on 2026-08-12, median
of seven repeats after a discarded warmup, 59.9 ms against 90.3 ms. Only the ratio survives
a different machine.

## Consequences

The policy is broad and its coverage is thin, and both halves of that are now printed by
`scripts/trace_report.py` rather than left for a reader to work out. A strategy for a code
nothing reaches is not dead code, because the code is reachable, but it is an untested
decision and the report says so every time it runs.
