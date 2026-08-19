# ADR 0003: The eval set is frozen before anything runs

Status: accepted

## Context

An eval set edited after the scores arrive measures nothing. The temptation is real and it
does not feel like cheating at the time. A question looks unfair. Or badly worded. Or the
system fails it for a reason that seems beside the point. Moving it feels like tidying up.

## Decision

`evals/FROZEN.json` holds a sha256 of `questions.jsonl` taken before any
generation code existed. `evals/freeze.py` verifies it and the test suite fails on a
mismatch. The error message says to revert the questions file and not to refresh the hash,
because the person about to do the wrong thing is the one reading that message.

Two changes were made before the hash was written and both are recorded here.

q006 asked which stores took more than 800 orders. No store took more than 536, so the
gold answer was empty. An empty gold answer is scored correct by any query that returns
nothing, including a broken one. The threshold moved to 500 and `gold.unscoreable` now
refuses to let an empty gold answer through.

Thresholds in the remaining questions were checked against the data so that no answer is
empty and none returns every row. Choosing a threshold from the data is fine. Choosing it
from a score is not, and no score exists yet.

## Consequences

Eight of the 30 questions expect a refusal, and two of those are a policy call about
personal data rather than one of the five guardrails the plan names. Those two may well go
unanswered at the end. They stay in. A question that scores badly is the only kind
worth having.

The set has 30 questions and 22 of them are scorable against a gold answer. Carrying
forward a finding from the previous project, a comparison between two systems needs at
least 6 questions to disagree before a two sided permutation test can reach p below 0.05.
That is 20 percent of the set. Anything smaller than that is not a result and the write-up has to
say so rather than reporting a gap that could never have been significant.
