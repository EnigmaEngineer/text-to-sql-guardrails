# text-to-sql-guardrails

Ask a question in English, get SQL, and have the agent refuse the query before it runs if
it is unsafe or too expensive. The guardrails are the product. The generation is the easy
part.

Day 2 of 7. There is no agent yet. What exists is the warehouse it will query and the
frozen question set it will be judged on. Day 2 adds a schema retrieval layer and the
measurement showing it does not pay on a schema this size.

```
python3 scripts/build_warehouse.py  --db /tmp/wh.duckdb
python3 scripts/check_gold.py       --db /tmp/wh.duckdb
python3 -m tests.run_all            --db /tmp/wh.duckdb
python3 scripts/retrieval_report.py --db /tmp/wh.duckdb --json /tmp/r.json
```

`requirements.txt` is duckdb and matplotlib. The embedding scorer needs
`requirements-dense.txt` on top, which is roughly 500 MB of wheels and a 130 MB model
download. Everything except that scorer runs without them, and the report prints a line
saying it ran without them rather than quietly showing a shorter table.

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
evals/power.py           smallest detectable difference, and the sign flip test
retrieval/relevance.py   which tables a question needs, read out of the gold sql
retrieval/lexical.py     idf weighted word overlap, no model
retrieval/dense.py       bge-small over the same table text
retrieval/graph.py       join edges inferred from primary key naming
retrieval/select.py      top k, join expansion, and what the prompt costs
docs/adr-000*.md         five decisions, with what each one costs
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

## Day 2, measured on 2026-08-08

Retrieval is meant to keep the prompt small on a wide warehouse. This warehouse is not
wide. The whole schema is 2,716 characters. So day 2 measured the layer instead of
assuming it.

Relevance is not hand labelled. A table is relevant to a question when the frozen gold SQL
for that question reads from it, and the tables are pulled out of DuckDB's own parse tree
rather than out of the query text. An alias, a CTE name and the word from inside a string
literal are all handled by the parser that will run the query.

The metric is `complete@k`. The share of questions where **every** required table was
retrieved. A question needing four tables that gets three is not three quarters right,
because the generated SQL cannot be correct at all. That makes it a ceiling on accuracy
rather than a score.

| retriever | k | complete | table recall | mean prompt chars |
|---|---|---|---|---|
| lexical | 8 | 18 of 22 | 0.905 | 1,242 |
| lexical + join | 8 | 21 of 22 | 0.976 | 2,126 |
| dense | 8 | 20 of 22 | 0.952 | 1,298 |
| dense + join | 8 | 20 of 22 | 0.952 | 2,288 |
| send everything | n/a | 22 of 22 | 1.000 | 2,716 |

The suite is 60 checks after today, up from 38. Every figure in this section came out of
`scripts/retrieval_report.py` on 2026-08-08, run from this repo rather than from the
scratch copy it was written in.

![retrieval cost against completeness](docs/retrieval_cost.png)

The best configuration gives up one question and saves 590 characters, which the report
prints as 21.7 percent. `docs/adr-0005` records the decision. Keep the layer and default it
off. Stop pretending it was needed here.

Every pairwise comparison at k=8 is underpowered and the report says so on the line where
it prints the number. The largest gap moves three questions, and this set needs six
disagreements before p below 0.05 is reachable at any effect size.

## What day 2 got wrong

**A one line change to the baseline destroyed the headline result.**

The first measurement had dense beating lexical 20 questions to 13 at k=8. Seven questions
differed and every one went the same way. The exact sign flip test returns 0.0156, which
is below 0.05 and is the smallest value 7 differences can produce. That is a real result by
every rule this project follows.

Then the lexical scorer got a plural stripper. Four words long. Questions say orders and
the table is called `fct_order_header`, so `fct_order_header` was being missed on seven
questions for no reason except that the baseline was sloppy. Four questions had scored zero
against every table in the schema.

After the fix the same comparison is 20 to 18. Two questions differ. The p value is 0.50.

The win was not the embedding. It was the plural.

Both tables came out of `scripts/retrieval_report.py`. The pre-fix one was regenerated by
reverting the stemmer, which is one of the mutants below, so neither number here rests on a
scratch script that no longer exists.

**Improving the scorer made the system worse.** `lexical + join` at k=8 went from 22 of 22
down to 21 of 22 after the same fix. Join expansion had been covering for the scorer's
misses, and a better scorer puts different tables in the top eight. A component that gets
better on its own can drag the thing it sits inside backwards.

That also flips the verdict on the layer, which is why `docs/adr-0005` states the verdict
carefully. Before the fix retrieval reached 22 of 22 and saved 523 characters, so it was
free. After it, retrieval costs a question to save 590. The prize is about 550 characters
either way, on a 2,716 character schema. A layer whose best case is smaller than the swing
caused by how its baseline handles plurals is not earning its keep here.

**`dim_date` cannot be found by anything here.** Six questions need it. None of them says
the word date. Its primary key is `date_key` while the fact tables carry `order_date_key`,
so the naming convention every other join follows breaks on the one dimension that is
needed most. Text scoring cannot see it and the inferred join graph gives it zero edges.
The inferred edges cover 9 of the 16 table pairs the gold queries put together.

## Mutation, day 2

14 mutants over the new modules, 13 killed. The survivor renames a local variable and is
the control.

The ones worth naming. Keeping CTE names as tables. Counting a partial hit as complete.
Breaking ties by catalog order rather than by name. A one sided permutation test. Flipping
the ties along with the differences. Dropping the plural stripper.

## Known limitations

**The Snowflake path has never run.** `adapter.snowflake()` carries `verified = False` and
a test asserts it. Every number in this repo comes from DuckDB.

**Retrieval loses on this warehouse and it is shipped anyway.** Measured, not argued. See
`docs/adr-0005`. It is kept because the guardrails on days 3 to 6 need a table set to
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
one side without saying so. Day 7 reports per question rather than hiding this in a single
accuracy figure.

**The generator is not the real world.** Order status is drawn from a fixed list, so the
cancellation rate is a constant this repo chose. Nothing measured against this warehouse
says anything about real retail data.

## Mutation

The test suite is checked by breaking things on purpose. Day 1 ran 12 mutants and killed
11. Day 2 ran 14 more over the new modules and killed 13. Both survivors are deliberate
no-op controls, there to prove the runner is not failing everything it is handed.

The one real survivor on the day 1 pass was the cell ordering mutant above. It is now
killed.
