# Limitations

Moved out of the README so the front page stays short. Back to the [README](../README.md).

## Known limitations

**No model has ever been called.** There is no API key and no local weights in the
environment this repo is built in, so `agent/generate.py` ships three fixtures and a
backend that refuses. Nothing here says anything about how well a model writes SQL.

**Nothing stops a PII read.** `SELECT customer_email FROM retail.dim_customer` is a single
read over a real table and a real column, so it passes the gate and it passes static
validation too. It is what question q026 asks for. A column level policy is the obvious
answer and nothing in the plan asked for it. Validation made this gap narrower and not
smaller.

**Static validation checks names and not types.** `CAST(customer_email AS INTEGER)` is
approved by both layers and fails at execution. That outcome is reported as `failed`
rather than `refused`, and the correction loop sends a different message back for each.

**Eleven of the fourteen correction strategies have never met a real input.** They are
reachable, so this is not dead code. It is eleven untested decisions about what to tell a
model, and nothing in the eval set exercises any of them. Widening the eval set is the
honest fix and I did not have room for it.

**The corrections have never been read by a model.** `SequenceGenerator` answers from a
list and ignores what it is told. So the loop, the trace and the four stopping rules are
exercised on real refusals from real layers, and whether a correction actually helps is
not measured anywhere in this repo. No number here claims it does.

**Bare columns under a CTE or a subquery are skipped, not checked.** Those names can be
bound inside the query and resolving them properly means implementing name resolution.
Over the answer key it is 112 column references checked and 8 skipped. The count is
printed rather than hidden, because a validator that quietly stops checking is worse than
one that says how much it looked at.

**Extension loading is allowed and was not pursued.** `INSTALL httpfs` and `LOAD httpfs`
both succeed on the read-only connection. Whether a remote file sink then works from this
sandbox was not tested, because testing outbound exfiltration is not a thing to do
casually. The claim here is only that the extension loads.

**The cost ceiling reads an estimate, and an estimate is not a bound.** It came in under
what the query really scanned on 8 of the 22 gold queries. Anything the optimizer
underestimates walks under the ceiling. This stops accidents.

**Nothing caps the size of the answer.** The plan will not estimate rows returned, so
`SELECT * FROM retail.fct_web_session` passes every layer. A `LIMIT` injected on approved
SQL is the obvious answer and it is a change to the query rather than a judgement about it,
which is a different kind of act and belongs behind a decision rather than inside a
commit.

**The Snowflake path has never run.** `adapter.snowflake()` carries `verified = False` and
a test asserts it. Every number in this repo comes from DuckDB. `cost.read_plan` is written
against DuckDB's plan document and Snowflake returns a different one, so the cost layer does
not port either.

**Retrieval loses on this warehouse and it is shipped anyway.** Measured, not argued. See
`docs/adr-0005`. It is kept because the guardrails downstream need a table set to
validate against and because a wide warehouse is the case this project is written for. It
is off by default.

**The relevance labels inherit whatever is wrong with the gold SQL.** They are derived
from it, so a gold query that reads a table it does not need makes that table relevant
forever. That is better than a hand written list, which would have the same problem plus a
second author. It is not independent.

**The join graph is inferred from column naming and nothing validates it properly.**
`edge_agreement` compares it against tables that co-occur in a gold query, and two tables
in one query might be joined to each other or might both be joined to a third. The number
it gives, 9 of 16, is a lower bound on a quantity that is itself an upper bound.

**No token budget, still.** Characters are measured because the tokeniser belongs to a
model that has not been chosen. See `docs/adr-0004-no-token-budget-yet.md`.

**k is not the number of tables that reach the prompt once join expansion is on.**
`lexical + join` at k=8 sends 2,126 characters, which is most of the schema. The character
column is the honest axis and k is only a knob. Comparing two retrievers at equal k is not
comparing them at equal cost.

**k stops at 8 and there is nothing special about 8.** With 18 tables, a large enough k
retrieves everything and the metric goes to 1.0 by definition. The curve is bounded on the
right by the whole schema and the chart shows that boundary rather than hiding it.

**`edge_agreement` is a weak check on a weak quantity.** It also does not distinguish a
one hop path from a two hop one, so 9 of 16 understates a graph that may still reach the
missing pairs. It is the only validation available without hand writing a foreign key list,
which would be a second thing to get wrong.

**No FAISS, despite the project plan naming it.** Eighteen vectors is a dot product against
a matrix with eighteen rows. An index here would be a dependency that does nothing.

**Zero answer collisions is a fact about these 22 numbers, not a property.** 7 of the 22
answers are a single cell. Change the seed and a collision is plausible. The test suite
checks it every run for that reason.

**The eval set is inconsistent about cancelled orders and it is now frozen.** Fourteen of
the gold queries touch the order tables. Five exclude cancelled orders and nine do not.
There is no stated rule, so a system has no way to infer which questions want the filter.
Some of the nine are defensible, because an order placed and then cancelled was still
placed. `q005`, the average order total by channel, is a judgement call and the eval takes
one side without saying so. The scorecard reports per question rather than hiding this in a
single
accuracy figure.

**The generator is not the real world.** Order status is drawn from a fixed list, so the
cancellation rate is a constant this repo chose. Nothing measured against this warehouse
says anything about real retail data.

## What I would do next, and why it is not here

Five things were tracked all week as decisions owed by the last day. Four of them are not
built. That is the answer rather than a delay, and each one says what it would cost.

**A column level policy, so a PII read is refused.** This is the largest gap and it is
first. `SELECT customer_email FROM retail.dim_customer` passes every layer, because it is
one read of a real column of a real table. Two frozen questions ask for exactly that. The
cheap version is a deny list checked against the parse tree the gate already builds, and it
is about twenty lines that would take refusal coverage from 5 of 8 to 7 of 8. **That is
precisely why it is not here.** Closing a measured gap with twenty lines on the final day,
to move a number the same day that number is published, is the one thing this repo spent
seven days not doing. The honest version needs a policy model with a subject and a purpose
attached to a query, and nothing in the plan earned one. `docs/adr-0006` has the argument.

**Foreign keys in the schema, so the join graph reads a fact instead of guessing.**
`warehouse/schema.sql` declares primary keys and no foreign keys, so
`retrieval/graph.py` infers edges from column naming. It breaks on `dim_date`, whose key is
`date_key` while the fact tables carry `order_date_key`. Six scored questions need that
table and not one contains the word date, so no scorer reaches it either. Adding the
constraints means rebuilding the warehouse, which changes the gold answers that every
number in this file rests on. The freeze hash covers the questions and not the
schema, so it is permitted and it is still the wrong week to do it. It is the first thing a
second week does, together with a re-verification of all 22 gold fingerprints.

**A gate interface on the adapter, or a plainer statement that the guardrails do not
travel.** All three layers are DuckDB shaped. The parser gate and the validator both go
through `json_serialize_sql`, and the cost layer reads DuckDB's plan document.
`adapter.snowflake()` carries a case folding rule and an `EXPLAIN` prefix and says nothing
about gating. Writing an unverified Snowflake gate alongside the verified DuckDB one is the
worse option, because a safety component that has never run is worse than an absent one. So
the README states the limit and `adapter.snowflake().verified` is `False` with a test
asserting it.

**A second, unfrozen probe set, so the correction policy stops being mostly untested.**
Eleven of the fourteen retry strategies have never met an input from outside the test
suite. Growing the frozen set is the natural fix and `docs/adr-0003` forbids it, because
the freeze hash is what makes every earlier number comparable. `evals/reach.PLAUSIBLE` is
already an unfrozen probe set in miniature and growing it is the shape of the answer. It is
a day of work and it belongs to whichever project needs those codes to be real.

**The self join defect.** This one was built, on the last day, and it turned out to hide a
second defect of the same kind. See the scorecard section.
