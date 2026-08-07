# text-to-sql-guardrails

Ask a question in English, get SQL, and have the agent refuse the query before it runs if
it is unsafe or too expensive. The guardrails are the product. The generation is the easy
part.

Day 1 of 7. There is no agent yet. What exists is the warehouse it will query, the frozen
question set it will be judged on, and the four decisions that constrain the rest of the
week.

```
python3 scripts/build_warehouse.py --db /tmp/wh.duckdb
python3 scripts/check_gold.py      --db /tmp/wh.duckdb
python3 -m tests.run_all           --db /tmp/wh.duckdb
```

The database goes outside the repo when this runs in a sandbox. A DuckDB checkpoint
unlinks its write ahead log and some mounts refuse unlink. On a laptop the default path
`warehouse/retail.duckdb` is fine.

## What is here

```
warehouse/schema.sql     18 tables, 111 columns, retail order model
warehouse/seed.py        deterministic generator, one seeded Random
warehouse/catalog.py     reads the catalog out of the live database
warehouse/adapter.py     DuckDB and Snowflake dialect records
evals/questions.jsonl    30 questions, frozen
evals/gold.py            runs the gold SQL, canonicalises a result set
evals/collision.py       how often two questions share an answer
evals/power.py           smallest difference this set could detect
evals/freeze.py          the hash that stops the questions moving
docs/adr-000*.md         four decisions, with what each one costs
```

## Measured on 2026-08-07

Every figure below came out of a command run that day. Rebuild them with the three
commands above.

| what | value | from |
|---|---|---|
| warehouse rows | 208,969 | `scripts/build_warehouse.py` |
| build time | 0.90 s | same |
| tables, columns | 18, 111 | `scripts/check_gold.py` |
| whole schema as prompt text | 2,716 chars | same |
| largest single table rendering | 237 chars | same |
| questions | 30 | `evals/questions.jsonl` |
| scorable against a gold answer | 22 | same |
| gold queries, total runtime | 22, 0.044 s | `scripts/check_gold.py` |
| answers that are one row and one column | 7 | same |
| questions sharing an answer | 0 | same |
| checks, and how many pass | 38, 38 | `python3 -m tests.run_all` |
| mutants killed | 11 of 12 | see below |
| gold answers identical across two independent builds | 22 of 22 | two builds, fingerprints compared |

Timings are from one machine on one day. The ratios survive, the milliseconds do not.

## The eval set

30 questions. 22 have a gold SQL query and are scored on the answer. 8 expect a refusal.

| expected refusal | count | which guardrail should catch it |
|---|---|---|
| write_operation | 3 | read-only role, day 3 |
| unbounded_scan | 2 | cost ceiling, day 5 |
| pii_export | 2 | nothing yet |
| not_in_schema | 1 | static validation, day 4 |

Two of those eight are a policy call about personal data and the plan for this project
names no policy layer. They may go unanswered at the end of the week. They stay in.

The set is frozen. `evals/FROZEN.json` holds a sha256 taken before any generation code
existed and the test suite fails if the questions file moves.

## What day 1 got wrong

Two things, both caught before the freeze and before the commit.

**q006 had an empty gold answer.** It asked which stores took more than 800 orders. The
busiest store took 536. An empty result set is scored correct by any query that returns
nothing, including one that read the wrong table. The threshold moved to 500 and
`gold.unscoreable` now refuses to freeze a set containing an empty gold answer.

**Result equality and result hashing disagreed about booleans.** Python says `True == 1`,
so a boolean answer compared equal to a count of one while their fingerprints differed.
The collision detector groups by fingerprint. Booleans are now tagged and a test asserts
that equality and fingerprint agree on every pair of gold answers.

A third came out of the mutation run. Sorting the cells inside a row survived every check
in the suite. A revenue and month pair would have scored equal to the same two values the
other way round. That check now exists.

A fourth was a label. `power.describe` printed the number 30 next to the word scorable
while only 22 of the questions are scored against a gold answer. Both counts are real and
they mean different things, so it now prints both.

## Known limitations

**The Snowflake path has never run.** `adapter.snowflake()` carries `verified = False` and
a test asserts it. Every number in this repo comes from DuckDB.

**Retrieval is being built for a problem this warehouse does not have.** The whole schema
renders in 2,716 characters. It fits in a prompt. Day 2 either widens the warehouse until
schema retrieval earns its place or measures what the layer costs on a schema that never
needed it. See `docs/adr-0004-no-token-budget-yet.md`.

**Zero answer collisions is a fact about these 22 numbers, not a property.** 7 of the 22
answers are a single cell. Change the seed and a collision is plausible. The test suite
checks it every run for that reason.

**The eval set is inconsistent about cancelled orders and it is now frozen.** Fourteen of
the gold queries touch the order tables. Five exclude cancelled orders and nine do not.
There is no stated rule, so a system has no way to infer which questions want the filter.
Some of the nine are defensible, because an order placed and then cancelled was still
placed. `q005`, the average order total by channel, is a judgement call and the eval takes
one side without saying so. Day 7 reports per question rather than hiding this in a single
accuracy figure.

**The generator is not the real world.** Order status is drawn from a fixed list, so the
cancellation rate is a constant this repo chose. Nothing measured against this warehouse
says anything about real retail data.

## Mutation

The test suite is checked by breaking things on purpose. 12 mutants, 11 killed. The
survivor is a deliberate no-op control, there to prove the runner is not failing
everything it is handed.

The one real survivor on the first pass was the cell ordering mutant above. It is now
killed.
