# text-to-sql-guardrails

Ask a question in English, get SQL, and have the agent refuse the query before it runs if
it is unsafe or too expensive. The guardrails are the product. The generation is the easy
part.

Day 4 of 7. The agent runs end to end against a scripted generator, because no model is
reachable from the environment this is built in. Day 4 adds static validation against the
live catalog and the measurement showing what the day 3 gate was letting through.

```
python3 scripts/build_warehouse.py  --db /tmp/wh.duckdb
python3 scripts/check_gold.py       --db /tmp/wh.duckdb
python3 -m tests.run_all            --db /tmp/wh.duckdb
python3 scripts/retrieval_report.py --db /tmp/wh.duckdb --json /tmp/r.json
python3 scripts/validation_report.py --db /tmp/wh.duckdb --json /tmp/v.json
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
agent/role.py            the read-only role, and the gate that has to sit in front of it
agent/prompt.py          prompt construction, in named sections that can be measured
agent/generate.py        the generator interface, and parsing what comes back
agent/pipeline.py        one question in, one attempt out, every step recorded
agent/validate.py        static validation against the catalog the query will run on
agent/guard.py           gate then validate, the only door to the connection
scripts/role_probe.py    what a read-only connection actually blocks
scripts/validation_report.py  what each layer catches, and what ran without it
docs/adr-000*.md         seven decisions, with what each one costs
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

## Day 3, measured on 2026-08-09

Every figure below was produced by a script in this repo on that date. The commands are
named beside them so they can be re-run rather than trusted.

**A read-only connection is not a read-only process.** `python3 scripts/role_probe.py`
runs each statement against a read-only copy of the warehouse. Anything refused is then
retried against a writable copy, so a refusal caused by bad SQL in the probe is reported
as invalid rather than counted as a protection.

| statement | read-only connection |
|---|---|
| INSERT, UPDATE, DELETE, CREATE, DROP, ALTER | blocked |
| CREATE TEMP TABLE, SET memory_limit | allowed |
| `COPY (SELECT ...) TO 'file.csv'` | **allowed** |
| `EXPORT DATABASE 'dir'` | **allowed** |
| `read_csv('/etc/hostname')` | **allowed** |
| `INSTALL httpfs` then `LOAD httpfs` | **allowed** |
| `SELECT 1; COPY (...) TO 'file.csv'` | **allowed** |

Five of the fifteen statements probed were allowed and act outside the database. The
read-only role protects the warehouse. It does not protect the data in it.

`EXPORT DATABASE` on the read-only connection wrote 23 files to disk covering all 208,969
rows. The stacked statement returned a row count and left a file holding 4,000 customer
email addresses. Two of the eval set's refusal questions are tagged `pii_export`.

So the connection is the second layer. The first is a gate that asks DuckDB to serialize
the SQL and approves it only when the serializer succeeds and there is exactly one
statement. See `docs/adr-0006-read-only-is-not-enough.md`.

**Prompt size**, from `python3 scripts/generation_report.py`, over the 22 answerable
questions. Min 3,292 characters, mean 3,304, max 3,317. The schema block is 2,716 of that
and does not vary, because retrieval is off by default per `adr-0005`.

**Refusal coverage.** Eight questions expect a refusal and three of them are reachable by
anything built so far.

| reason | questions | status | needs |
|---|---|---|---|
| write_operation | 3 | covered | day 3, the gate |
| not_in_schema | 1 | open | day 4, static validation |
| unbounded_scan | 2 | open | day 5, the cost ceiling |
| pii_export | 2 | open | nothing designed yet |

The three covered ones were run through the pipeline with the obvious write SQL for each
and all three came back refused. That SQL was written by hand, so it demonstrates the gate
and does not measure a model.

**There is no accuracy number here and there will not be one until day 7.** No language
model is reachable from the environment this repo is built in. Generation runs through
`ScriptedGenerator`, which replays the frozen gold SQL. The 22 of 22 that
`generation_report.py` prints is a statement about the plumbing and about nothing else.

## What day 3 got wrong

**The role probe reported three protections that had not been tested.** The first version
had INSERT, UPDATE and COPY coming back refused, and the reason in each case was a binder
error about a column that does not exist. The SQL in the probe was malformed. All three
fail the same way on a writable connection, so the probe was reporting the read-only role
blocking statements it had never actually been shown. Rewritten to retry every refusal
against a writable copy and label it `INVALID` when both refuse. Fixing that flipped
`COPY TO file` from blocked to allowed, which is the finding the whole day rests on.

**A test asserted the wrong refusal reason and it was the test that was wrong.** The
stacked exfiltration comes back as `not_a_read`, not `multiple_statements`, because the
serializer fails on the whole string as soon as one statement in it is not a SELECT. The
query is still refused. `multiple_statements` only fires when every statement is a read,
which the two-select check covers.

**The question splitter broke on a question containing the word it splits on.** A question
reading "What does Question: mean in the ticket table?" came back as "mean in the ticket
table?". It now anchors on the blank line between prompt sections. The fixture that caught
it was written because a marker that can appear in the payload is the obvious thing to get
wrong, and it caught it on the first run.

**A duplicate class name.** `NotConfigured` was written twice in one module, once as an
exception and once as a generator, so the second silently replaced the first. Caught by
reading the file before running it.

**The probe under-reported what it had written.** It listed files with `os.listdir`, and
`EXPORT DATABASE` writes a directory, so the row that dumps the entire warehouse showed as
having left nothing behind.

## Mutation, day 3

14 mutants over the new modules, 13 killed. The survivor renames a local variable and is
the control.

The ones worth naming. Dropping the zero statement check. Dropping the multiple statement
check. Collapsing `unparseable` into `not_a_read`. Reverting the question splitter to the
bare marker, which is today's bug turned into a regression test. Testing the refusal token
by substring instead of equality. Reporting a gate refusal as an execution failure.

## Day 4, measured on 2026-08-10

Static validation against the catalog, plus the injection check the blueprint asks for.
Rebuild every number below with:

```
python3 scripts/build_warehouse.py    --db /tmp/wh.duckdb
python3 -m tests.run_all              --db /tmp/wh.duckdb
python3 scripts/validation_report.py  --db /tmp/wh.duckdb --json /tmp/v.json
python3 scripts/validation_chart.py   --json /tmp/v.json
```

**The day 3 gate approves a query that reads the host filesystem.** It is a single SELECT,
so it serializes, so the gate says yes and the read-only connection runs it.

```
list the filesystem     gate allows   ran, 95 rows, first cell '/etc/.pwd.lock'
read a host file as text gate allows  ran, 1 rows, first cell '/etc/hostname'
```

The day 3 probe had already recorded that `read_csv` on a path works on a read-only
connection. The gate written the same day was never pointed at it.

![what each layer catches](docs/gate_vs_validation.png)

Over 17 probe queries, the day 3 gate alone approves 14. Static validation refuses 12 of
those 14. The two it lets through are correct queries and it should.

**The obvious validator would not have caught the worst one.** A table function is not a
`BASE_TABLE` in the parse tree, so a check that walks base tables and looks each one up
finds an empty list and reports no problem. The most dangerous query in the set gives the
check the least to do. So `no_relation` is a finding here. A query that reads no table in
the warehouse is refused, `SELECT 42` included.

**What it refuses, by code.**

| code | what it means |
|---|---|
| `table_function` | `read_csv`, `glob`, `read_text` and anything else that reads a path |
| `unknown_table` | a base table that is not in the catalog |
| `unknown_column` | a column that is not in the table it is attributed to |
| `cross_join` | an explicit cross join, or a comma join, over warehouse tables |
| `implicit_join` | a natural join, whose keys change when a column is added |
| `unrelated_join` | a join whose condition does not mention both sides |
| `no_relation` | the query reads nothing in the warehouse |
| `unparseable` | it will not parse, reported rather than raised |

**Cost.** `guard.approve` over the 22 gold queries is 12.56 ms, which is 0.571 ms per
query and 51.2 percent of the 24.54 ms it takes to run the same 22. That ratio is a
statement about a warehouse where the average query finishes in about a millisecond. On
anything with real data in it the approval cost stops mattering. Timings taken 2026-08-10
on the sandbox and only the ratio survives a different machine.

**Refusal coverage on the frozen eval set is 4 of 8, up from 3.** `q030` asks for a churn
score the warehouse does not hold and is now refused as `unknown_column`. `q029` is also
refused, by the cross join rule, and it is labelled `unbounded_scan`. Counting that as
cost coverage would be claiming a day 5 result on day 4. `q028` is the same category with
no cross join in it and nothing built so far touches it.

**One door.** `agent/guard.py` composes gate then validation and is the only path from
generated SQL to the connection. `role.run` was deleted rather than left as a second door.
`tests/test_guard.py` walks `agent/` with `ast` and fails if any `.execute()` outside
`guard.py` is handed anything but a string literal, because a literal cannot be model
output. A mutant that added `con.execute(sql)` to the pipeline broke 7 checks.

## What day 4 got wrong

**The first column rule refused 6 of the 22 gold queries.** All six the same way:

```sql
SELECT s.store_name, count(*) AS orders
FROM   retail.fct_order_header h
JOIN   retail.dim_store s ON s.store_id = h.store_id
GROUP  BY s.store_name
ORDER  BY orders DESC
```

`orders` is bound by the statement and will never be in the catalog. A guardrail that
refuses more than a quarter of correct queries does not get tightened. It gets switched
off, and then it protects nothing. Output aliases are now collected in the same walk.

**Three test queries were written against columns that do not exist.** The schema uses
`customer_id` and `order_status` and the fixtures said `customer_key` and `status`. The
validator was right and the tests were wrong, which is the good version of that failure.

**A mutant that let cross joins through survived.** Two branches produced the same code,
one for an explicit cross join and one for a join with no condition, so a test asserting
only the code could not tell which fired. The tests assert the detail now. Checking why
then showed the second branch is unreachable, because `a JOIN b` with no `ON` and no
`USING` is a syntax error. It was deleted.

**The mutation run exfiltrated 4,001 customer emails and then poisoned itself.** The
mutant that executed a refused verdict wrote them to the fixed path a test asserts is
absent. Every mutant after it looked killed, including the control, which is the one that
must survive for the run to mean anything. The test uses a unique temporary directory now.

## Mutation, day 4

17 mutants, 15 killed. The two survivors are the control, which rewords a comment, and one
that removes the string literal check from the one door test. Nothing tests a test, so
that second survivor is expected. What it would have caught was verified directly instead,
by adding a real second door to the pipeline and watching 7 checks go red.

Named ones that were killed. Allowing `read_csv` through the table function set. Dropping
the `no_relation` finding. Accepting every bare column. Treating output aliases as unbound
names. Reporting `ok` regardless of findings. Executing a refused verdict. Skipping the
gate refusal branch so validation ran first.

## Known limitations

**No model has ever been called.** There is no API key and no local weights in the
environment this repo is built in, so `agent/generate.py` ships three fixtures and a
backend that refuses. Nothing here says anything about how well a model writes SQL.

**Nothing stops a PII read.** `SELECT customer_email FROM retail.dim_customer` is a single
read over a real table and a real column, so it passes the gate and it passes static
validation too. It is what question q026 asks for. A column level policy is the obvious
answer and it is on no day of the plan. Day 4 made this gap narrower and not smaller.

**Static validation checks names and not types.** `CAST(customer_email AS INTEGER)` is
approved by both layers and fails at execution. That outcome is reported as `failed`
rather than `refused`, because day 6 has to send a different correction back for each.

**Bare columns under a CTE or a subquery are skipped, not checked.** Those names can be
bound inside the query and resolving them properly means implementing name resolution.
Over the answer key it is 112 column references checked and 8 skipped. The count is
printed rather than hidden, because a validator that quietly stops checking is worse than
one that says how much it looked at.

**Extension loading is allowed and was not pursued.** `INSTALL httpfs` and `LOAD httpfs`
both succeed on the read-only connection. Whether a remote file sink then works from this
sandbox was not tested, because testing outbound exfiltration is not a thing to do
casually. The claim here is only that the extension loads.

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
11. Day 2 ran 14 more over the new modules and killed 13. Day 3 ran 14 more and killed 13.
Day 4 ran 17 and killed 15. Every one of those survivors is a deliberate control except
the day 4 mutant of a test, which is described above.

The one real survivor on the day 1 pass was the cell ordering mutant above. It is now
killed.
