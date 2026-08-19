# ADR 0002: The eval scores the answer, not the SQL string

Status: accepted

## Context

Every question in `evals/questions.jsonl` carries a gold SQL query. The obvious scoring
rule is to compare the generated SQL against it. That rule is wrong. There are many
correct ways to write "revenue by month" and string comparison fails all but one of them.

## Decision

Run both queries and compare the result sets. `evals/gold.py` canonicalises a result
before comparing so that a `Decimal` and a `float` holding the same value agree.

Two things are deliberately kept rather than normalised away.

Row order stays. Three of the questions ask for a top N, and sorting the rows would let a
system score correct by returning the right rows backwards.

Column order stays. A mutation run found this. A version that sorted the cells
inside each row passed every other check and would have scored `(revenue, month)` as equal
to `(month, revenue)`.

Booleans are tagged. Python says `True == 1`, so an untagged boolean answer compared equal
to a count of one while the fingerprint of the two differed. Equality and hashing
disagreed, and the collision detector uses hashing.

## Consequences

The cost is answer collision. Two different questions can return the same thing, and when
they do, a system that generates the wrong query for one of them still scores correct.
`evals/collision.py` measures this rather than assuming it away.

Measured across the 22 answerable questions: zero colliding groups, and 7 answers
that are a single row and a single column. Those 7 are the exposure. A one cell answer is
far easier to reach by accident than a 20 row table.

Zero collisions is a property of these numbers, not a guarantee. The check runs in
the test suite so a future change to the seed cannot introduce one quietly.
