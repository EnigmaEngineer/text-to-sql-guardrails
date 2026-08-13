# ADR-0011: score the guard, because there is no model to score

Date: 2026-08-12 through 2026-08-13. Status: accepted.

## Context

The plan for day 7 says "README with accuracy numbers on the eval set." Accuracy on a
text to SQL set is a property of whatever writes the SQL. Nothing in this repo has ever
called a model. `agent/generate.py` ships two replay fixtures and a backend that raises,
and its docstring has said since day 3 that a score taken with a fixture is a statement
about that file.

So there are three ways to spend the last day.

1. Print an accuracy figure taken with `ScriptedGenerator`. It would be 22 of 22, because
   the fixture replays the answer key. It would also be a lie by construction.
2. Skip the number and write prose.
3. Score the thing that exists. The guard is what this project is about and it is what
   six days of work went into.

## Decision

Take the third. `evals/scorecard.py` runs all 30 frozen questions through the guard and
records one row each. No accuracy figure is printed anywhere, and
`scripts/scorecard_report.py` opens by saying why rather than leaving a gap someone fills
in later.

Three things follow from taking it seriously.

**The two halves are not the same kind of evidence and they are never pooled silently.**
The 22 answerable questions are run as their gold SQL. That half is in sample by
construction. Three checks in `tests/` fail the build if any layer refuses a gold query,
and day 4's first column rule refused six of them and was rewritten rather than accepted.
So the 22 record a green test. The 8 refuse-tagged questions are run as hand written
plausible SQL from `evals/reach.py`, which is the weak input and the only out of sample
half.

**Both degenerate arms are measured rather than argued.** `open_guard` approves
everything and `closed_guard` refuses everything. They are not systems. They are the
range any score on this set has to be read against, and the open arm is the floor.

**A raised exception is counted wrong.** It refused nothing and it took the caller with
it. An ablation that scored a crash as coverage would report the layer it had just
removed as unnecessary.

## What it measured

| arm | pooled, any refusal counts | out of 30 |
|---|---|---|
| refuse everything | 8 | 26.7 % |
| approve everything | 22 | 73.3 % |
| this repo | 27 | 90.0 % |

A system with no guardrails scores 73.3 percent, because the set holds 22 correct queries
against 8 that should be stopped. Everything six days of guardrails contributed is 5
questions.

On the half that could have gone badly it is 5 of 8 by the any reading and 4 of 8 by the
matching one. Eight observations do not support a percentage. The exact one sided 95
percent lower bound on 5 of 8 is 0.289.

## The ablation, and the one that surprised me

`guard.approve` grew a `layers` argument for this and for nothing else.

| layers | pooled | refused, any | refused, matching | raised |
|---|---|---|---|---|
| all three | 27 | 5 of 8 | 4 of 8 | 0 |
| no cost | 27 | 5 of 8 | 4 of 8 | 0 |
| no validate | 26 | 4 of 8 | 4 of 8 | 1 |
| no gate | 27 | 5 of 8 | 1 of 8 | 0 |
| gate only | 25 | 3 of 8 | 3 of 8 | 0 |
| validate only | 27 | 5 of 8 | 1 of 8 | 0 |
| cost only | 23 | 1 of 8 | 1 of 8 | 4 |

**Removing the cost layer changes nothing on this set.** A whole day of work, and the
frozen questions cannot see it. Day 5 said this in words. The ablation makes it a number,
and `check_taking_the_cost_layer_away_changes_nothing_on_this_set` pins it so that a
later change which makes the cost layer earn its place fails the suite and forces this
paragraph to be rewritten.

**Removing the parser gate also changes nothing under the reading this repo quoted for
five days.** Static validation refuses `DELETE` on its own. It comes back as
`unparseable`, because `json_serialize_sql` only serializes reads. Same score and the
wrong reason. The gate's whole contribution here is the reason, and the reason is only
visible in the matching reading. That is 4 of 8 with the gate and 1 of 8 without it. A
repo quoting one number would have concluded the gate was redundant.

**The cost layer alone raises on four questions instead of refusing them.** `EXPLAIN` on
a `DELETE` over a read-only connection is an `InvalidInputException`, and `EXPLAIN` on an
unknown column is a `BinderException`. Day 5 put cost last on the argument that `EXPLAIN`
binds and binding a table function opens what it points at. Here is the cruder second
reason. Run first, it does not refuse. It explodes.

## Costs

The `layers` argument is a way to turn the guard down and that is a real cost. It is
closed as far as it can be. An empty set raises rather than approving, an unknown name
raises, and `check_nothing_in_agent_passes_the_layers_argument` walks `agent/` with `ast`
and fails if any call site there ever uses it. The ablation is the only caller.

The 8 refusal questions are scored against SQL this repo wrote for them. A model would
write something else. `REFUSE_SQL_IS_HAND_WRITTEN` sits in the module and the report
prints it, because a caveat that lives in a limitations section has already been skipped
by the time it matters.

## What would produce a real accuracy number

A backend, a key, and a re-run on a machine that has both. The interface is there and
`NotConfigured` names the blocker. Nothing else in this repo needs to change, which is
the one good thing about having built the guard first.
