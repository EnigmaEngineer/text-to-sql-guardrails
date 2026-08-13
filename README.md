# text-to-sql-guardrails

Ask a question in English, get SQL and have the agent refuse the query before it runs if
it is unsafe or too expensive. The guardrails are the product. The generation is the easy
part.

Day 7 of 7, complete. The agent runs end to end against a scripted generator, because no
model is reachable from the environment this is built in.

**There is no accuracy number in this repo and there cannot be one.** Accuracy on a text
to SQL set is a property of the thing writing the SQL, and nothing here has ever called a
model. So day 7 scores the guard instead. Scored on all 30 frozen questions the guard gets
27, and a system with no guardrails at all gets 22. That gap is what six days of work
bought. `docs/adr-0011` is the whole argument.

```
python3 scripts/build_warehouse.py   --db /tmp/wh.duckdb
python3 scripts/check_gold.py        --db /tmp/wh.duckdb
python3 -m tests.run_all             --db /tmp/wh.duckdb
python3 scripts/retrieval_report.py  --db /tmp/wh.duckdb --json /tmp/r.json
python3 scripts/validation_report.py --db /tmp/wh.duckdb --json /tmp/v.json
python3 scripts/cost_report.py       --db /tmp/wh.duckdb --json /tmp/c.json
python3 scripts/trace_report.py      --db /tmp/wh.duckdb
python3 scripts/scorecard_report.py  --db /tmp/wh.duckdb --json /tmp/s.json
```

`requirements.txt` is duckdb and matplotlib. The embedding scorer needs
`requirements-dense.txt` on top, which is roughly 500 MB of wheels and a 130 MB model
download. Everything except that scorer runs without them and the report prints a line
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
agent/pipeline.py        one attempt in `answer`, the correction loop in `solve`
agent/validate.py        static validation against the catalog the query will run on
agent/cost.py            reads a plan, and the ceiling it is judged against
agent/guard.py           gate then validate then cost, the only door to the connection
agent/correct.py         one retry strategy per refusal code, derived from the source
agent/trace.py           every attempt and every correction, and a text renderer
evals/reach.py           which refusal codes anything but a test actually produces
evals/scorecard.py       all 30 questions, the two degenerate arms, and the ablation
scripts/role_probe.py    what a read-only connection actually blocks
scripts/validation_report.py  what each layer catches, and what ran without it
scripts/cost_report.py   the answer key, the two candidate metrics, and the probes
scripts/trace_report.py  the policy, what a retry costs, and what reaches it
scripts/scorecard_report.py  every question, the floor, and what each layer is worth
docs/adr-00*.md          eleven decisions, with what each one costs
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
| unbounded_scan | 2 | cost ceiling, day 5, and it does not catch them |
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

**Cost.** `guard.approve` over the 22 gold queries is 12.89 ms, which is 49.3 percent of
the 26.17 ms it takes to run the same 22. That is the day 4 shape, gate and validate with
no ceiling passed.

The number above described this layer correctly on 08-10 and stopped describing real use
on 08-11, when day 5 put `EXPLAIN` inside the same function. The pipeline always passes a
ceiling, and with the cost layer in, approval is 25.43 ms and 97.2 percent of execute.
Approving a query now costs about what running it costs. The original sentence here
concluded that approval cost stops mattering, and that conclusion did not survive the
layer that was added the next day.

Nothing produced the old figure, so nothing could catch it going stale. It is now printed
by `scripts/validation_report.py` on every run, both shapes side by side. Absolute numbers
move with the machine by up to 1.8x. The ratio is the part that travels.

**Refusal coverage on the frozen eval set is 4 of 8, up from 3.** `q030` asks for a churn
score the warehouse does not hold and is now refused as `unknown_column`. `q029` is also
refused, by the cross join rule, and it is labelled `unbounded_scan`. Counting that as
cost coverage would be claiming a day 5 result on day 4. `q028` is the same category with
no cross join in it and nothing built so far touches it.

> Read this as the matching reading. Day 6 found that the repo had been quoting one of two
> numbers without saying which. Five of the eight are refused by something and four are
> refused by the layer their label points at. Day 7 computes both from `scorecard.OWNER`
> rather than by subtracting one. See the day 7 section.

**One door.** `agent/guard.py` composes gate then validation and is the only path from
generated SQL to the connection. `role.run` was deleted rather than left as a second door.
`tests/structural.py` walks `agent/` with `ast` and fails if any `.execute()` outside
`guard.py` is handed anything but a string literal, because a literal cannot be model
output. A mutant that added `con.execute(sql)` to the pipeline broke 7 checks.

## Testing the tests

The one door check is the most important thing in the suite and for one day it was the
only thing here whose behaviour had never been demonstrated by anything but a person
trying it once. A mutant that pulled its teeth out survived, which is what happens when
nothing tests a test.

The detectors now live in `tests/structural.py` as ordinary functions over a path, and
`tests/fixtures/` holds small modules with defects planted in them and marked `# DEFECT`.
`tests/test_structural.py` asserts that the detector finds every marker and stays quiet
on the clean fixture. The manual demonstration became a check that runs every time.

Half of those fixtures exist for the opposite case, which is a detector handed nothing to
look at. There is a directory with no python in it, one holding nothing but the door, and
a module that makes no calls at all. Each must raise rather than report clean. Four checks
in this repo and its tooling have already passed by looking at nothing, most recently the
day 4 validator, which found no base tables in a query that read the host filesystem and
reported no problem.

Two things fell out of building it. A mutation run showed the string half of "must be a
string literal" was carrying no weight, because no fixture passed a constant that was not
a string. And the report was sorted as text, so a defect on line 23 was listed above one
on line 9. Both are fixed and both are now pinned by a fixture.

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

A later pass moved the detector into `tests/structural.py` and put fixtures under it. 14
mutants over the detector, 13 killed, and the one survivor is the control. The two that
had to be fixed rather than tested are described under "Testing the tests" above.

Named ones that were killed. Allowing `read_csv` through the table function set. Dropping
the `no_relation` finding. Accepting every bare column. Treating output aliases as unbound
names. Reporting `ok` regardless of findings. Executing a refused verdict. Skipping the
gate refusal branch so validation ran first.

## Day 5, measured on 2026-08-11

A cost estimate from `EXPLAIN`, and a ceiling that refuses a query before it runs.
Rebuild every number below with:

```
python3 scripts/build_warehouse.py --db /tmp/wh.duckdb
python3 -m tests.run_all           --db /tmp/wh.duckdb
python3 scripts/cost_report.py     --db /tmp/wh.duckdb --json /tmp/c.json
python3 scripts/cost_chart.py      --db /tmp/wh.duckdb --out docs/day5_cost_metric.png
```

**The obvious metric does not work and the second obvious one does not either.** Rows
returned to the caller is what anyone would want to cap. The plan will not give it. Over
the 22 gold queries the root node carries no estimate on 9 and reports exactly 0 on
another 11, against real answers of 4, 12 and 20 rows.

So the ceiling reads work done. Which of two ways is a measurement, not a preference.

| metric | answer key, worst case | inequality join | separation |
|---|---|---|---|
| sum of the scan nodes | 70,523 | 104,357 | 1.48x |
| largest estimate on any node | 64,357 | 223,844,302 | 3,478x |

The inequality join is `fct_order_line JOIN fct_web_session ON l.quantity > s.page_views`.
Its condition names two real tables, so day 4 approves it. Summing the scans puts it 1.48x
above the answer key, which is not a gap anything can sit in. The largest single step puts
it 3,478x above. Same plan, same walk, two numbers.

Ceiling is 208,969, the sum of `duckdb_tables().estimated_size` across the schema. It
comes off the warehouse rather than out of the eval set on purpose. No question anyone
types should make the engine handle more rows than the warehouse holds. It lands at 3.2x
the answer key worst case, which is headroom rather than calibration.

![the metric choice, and the estimate against reality](docs/day5_cost_metric.png)

**The estimate is not an upper bound.** Against DuckDB's own profiler it came in below
what the query really scanned on 8 of the 22 gold queries, worst at 0.23 of actual. This
layer refuses accidents. It is not a defence against someone trying.

**It buys no coverage on the eval set, and that is the honest headline.** Two questions
are tagged `unbounded_scan`. q029 was already refused by the day 4 cross join rule. q028
asks for every row of `fct_web_session` and estimates at 40,000. q009 is a real question
that reads the same table with no filter and estimates at 40,000 too. The plans cost the
same. No ceiling separates them, because what makes q028 unreasonable is the size of the
answer and that is the number the plan will not give. Refusal coverage stays at 4 of 8.

| after day 5 | refusal coverage |
|---|---|
| write_operation | 3 of 3, gate |
| not_in_schema | 1 of 1, validation |
| unbounded_scan | 0 of 2 by cost, 1 of 2 counting the day 4 cross join rule |
| pii_export | 0 of 2, still nothing |

`docs/adr-0009` records the decision and both of the wrong turns below. Day 7 took the
layer out entirely and scored the set again. The pooled figure does not move by a single
question, which is what this paragraph said in words and could not say as a number.

## What day 5 got wrong

Three times today a rule looked correct until it met an input the answer key does not
contain. That is the same mistake day 4 made with the output alias and it arrived in three
new costumes.

**The unscored operator list was written from memory and both halves were wrong.** It
named `CROSS_PRODUCT` and `NESTED_LOOP_JOIN`. A `NESTED_LOOP_JOIN` carries an estimate, so
that entry could never have fired. A join on a function of both sides plans as
`BLOCKWISE_NL_JOIN`, which carries none and was not in the list. The list is now inverted
and derived from the answer key. Four operators appear with no estimate across the 22 gold
queries. They are `ORDER_BY` and `UNGROUPED_AGGREGATE` and `PERFECT_HASH_GROUP_BY` and
`TOP_N`, and every one of them reduces or preserves rows. Anything else with no estimate is
refused.

**A correct query was refused for having no scan in its plan.** `SELECT count(*) FROM
retail.dim_store` plans as one `COLUMN_DATA_SCAN` estimated at 1, because DuckDB answers it
from metadata and never touches the table. No gold question is a bare count on one table,
so the answer key check stayed green while this was live. The rule now refuses a plan where
no node carries a number, which is a different question from whether a table was read.

**The day 4 structural check refused this day's first draft, correctly.** The ceiling was
first computed by building a `count(*)` per table with string formatting, which is a
non literal `.execute()` outside `agent/guard.py`. The suite went red on two checks. The
fix was not an exemption. `duckdb_tables()` gives the same total in one literal statement,
and `estimated_size` is the number the planner puts on a scan node, so the ceiling and the
thing measured against it now come from one source.

**Adding a third layer made the trace lie about the second.** The pipeline marked the
validate step with `verdict.allowed`, which was right while approval had two layers and
became wrong the moment a cost refusal could follow a clean validation. A query refused on
cost was reporting validation as failed. Caught by a check that reads the steps rather than
the outcome.

## Day 4 has a false positive it does not know about

Not fixed today, because it is a day 4 rule and the fix is a design question rather than a
patch. `unrelated_join` refuses any join whose condition touches fewer than two distinct
tables. A self join always resolves both aliases to one table, so every self join is
refused, including this one:

```sql
SELECT count(*) FROM retail.fct_order_header a
JOIN retail.fct_order_header b ON a.customer_id = b.customer_id AND a.order_id < b.order_id
```

That is a repeat purchase question and it is legitimate. No gold query self joins, which is
why day 4 shipped without seeing it. Same shape as everything above.

> Fixed on day 7. The rule counts qualifiers rather than tables now. A second false
> refusal of the same kind was found in the fix itself by a surviving mutant. See the day
> 7 section.

## Mutation, day 5

15 mutants over `agent/cost.py`, the cost branches of `agent/guard.py` and the new step in
`agent/pipeline.py`. 13 killed on the first pass. One survivor was the control. The other
was real and is now killed, taking it to 14 of 15.

The real survivor flipped the `no_estimate` refusal in `guard.approve` into an approval and
the whole suite stayed green. The branch is unreachable through the real path, because
validation refuses a query that reads no table before cost ever sees one. It is still right
to have, since without it `read_plan` raises out of a `guard.execute` documented never to
raise. So it got a test that stubs the plan rather than a deletion. That is the opposite
call from the day 4 survivor, which was an unreachable branch that really should have gone.

Named ones that were killed. Reading the scan sum instead of the largest step. Moving the
ceiling comparison off by one. Deleting the unscored operator rule. Adding `CROSS_PRODUCT`
to the safe list. Approving an empty plan. Approving a plan where nothing carries a number.
Dropping the check that a ceiling is positive. Taking the ceiling from one table instead of
the schema. Running cost before validation. Skipping cost whenever a ceiling was supplied.
Dropping the ceiling on the way through `guard.execute`. Reporting the validate step with
the final verdict.

## Day 6, measured on 2026-08-12

Day 6 of the plan is the self correction loop, capped at two retries, and trace capture.
`agent/pipeline.solve` runs the loop and calls `agent/pipeline.answer` and nothing else,
so every attempt goes through the same one door as a single attempt does.

```
python3 scripts/trace_report.py --db /tmp/wh.duckdb
python3 -m tests.run_all         16 modules, 217 checks, 217 passed
```

**The retry policy is one strategy per refusal code and the code list is read out of the
source.** `tests/test_correct.py` walks `agent/` with `ast`, pulls every refusal code
built from a string literal, and fails when one has no strategy or when a strategy exists
for a code nothing produces. There are fourteen.

**Three refusals are not coached at all.** `not_a_read`, `multiple_statements` and
`table_function` end the trace with nothing sent back. That is a security position rather
than an efficiency one. A write, a chained statement and a host file read are not slips,
and a correction there hands whatever produced the query another turn at the same target.
The cost is that a model which wrote a `DELETE` by accident does not get to fix it.

**Only three of the fourteen codes are produced by anything other than a test.**

| | count |
|---|---|
| refusal codes the agent can produce | 14 |
| coached | 11 |
| carrying a fact the prompt did not | 4 |
| produced by the eval set rather than by a test | 3 |

The four are `unparseable`, `over_ceiling`, `unscored_operator` and `no_estimate`. Those
come from the parser and the planner. The other ten are properties of a query read against
a schema that went into the prompt in full, so the correction points at a mistake rather
than telling the model anything it could not already have worked out.

`scripts/trace_report.py` prints the reach figure every run, because a strategy for a code
nothing reaches is an untested decision and it should not be able to hide inside a table
of fourteen.

**A full retry budget costs about 1.5x a clean run rather than 3x.** From
`scripts/trace_report.py` over the 22 answerable questions. Median of seven repeats after
a discarded warmup. 70.3 ms against 102.6 ms, spread 66.4 to 73.5 and 98.9 to 106.4, a
ratio of 1.46. A refused attempt is judged and never executed, which is where the missing
1.5x went. The ratio read 1.46, 1.49 and 1.51 across three passes today and the
milliseconds moved more than that, because the sandbox varies by roughly 1.8x between
days. Only the ratio travels.

**The loop stops on a repeat and not only at the cap.** The cap bounds the damage. It does
not stop a generator that ignores the correction, and a generator that ignores the
correction returns the same string, which is refused for the same reason by the same
layer. Four endings are recorded and kept apart: `resolved`, `stopped_unretryable`,
`stopped_repeated` and `stopped_at_cap`.

**The trace renders as text, not as a Streamlit app.** The plan names Streamlit. There is
no browser in the environment this repo is built in, and a component that has never run is
worse than an absent one. `docs/adr-0010` records that with the rest of the day.

```
attempt 1 of 3
  sql      SELECT favourite_colour FROM retail.dim_customer
  prompt   ok    3270 chars
  gate     ok    single_read
  validate FAIL  unknown_column
  outcome  refused (unknown_column)
  -> sent back: unknown_column: favourite_colour is not a column of dim_cus...

attempt 2 of 3
  sql      SELECT count(*) AS n FROM retail.dim_customer
  prompt   ok    3486 chars, 214 of correction
  validate ok    clean
  execute  ok    1 rows
  outcome  answered (1 rows)

ending   resolved after 1 retry(s)
```

![the correction policy and what reaches it](docs/day6_policy.png)

## What day 6 got wrong

**A report announced PII coverage this project does not have, on the strength of a typo.**
`evals/reach.py` runs a hand written plausible query for each of the eight refuse-tagged
questions. The first version asked `dim_customer` for `customer_name` and `dim_employee`
for `employee_name`. Both tables call that column `full_name`. So q026 and q027 came back
refused as `unknown_column` and the report counted them as covered, while the limitations
section below says plainly that nothing here stops a PII read. A name error was reading as
a control. `Reach.suspect` now flags any name error outside the one question tagged
`hallucination`, and a check runs every plausible query through the validator.

**A retry cost was measured once and reported as 1.20x.** The first `solve` of a process
pays for the catalog read and the planner warming, and that landed entirely on the single
attempt arm because it ran first. Warmed up and repeated seven times it is about 1.5x.

**A test compared two broken things and passed.** The check that an empty correction does
not change the prompt built one prompt with no correction and one with an empty string,
then asserted they matched. Both carried the mutation, so it passed against the mutant it
was written for. It now asserts on the text, where a dropped section shows up as a longer
run of newlines. That is an eighth distinct way something has passed here while being
wrong.

**The refusal coverage figure depends on an unstated convention.** The repo has been
quoting 4 of 8. Five of the eight are refused by something. The difference is q029, which
is labelled `unbounded_scan` and is stopped by the day 4 cross join rule, so the reading
that counts a question as covered only when the layer matching its label catches it gives
4 and the reading that counts any refusal gives 5. Both are now printed side by side, with
the reason, so the number cannot be quoted without the convention attached.

## Mutation, day 6

Thirty mutants in two rounds, over the six modules day 6 touched. The first round of
seventeen killed all seventeen. That was too clean to believe, so a second round of
thirteen was aimed at code the first had not touched. Six survived it and none was an
unreachable branch.

Two of the six were the day 5 shape, which is a branch contributing nothing today that
must stay anyway. Both got a stubbed test rather than a deletion. One is the loop running
the answer key through the guard. It fires only when a guardrail starts refusing correct
queries. The other is the second entry in `NAME_ERROR_CODES`, which nothing currently
trips. After the six fixes both rounds kill everything.

## Day 7, measured on 2026-08-13

The plan for today says "README with accuracy numbers on the eval set". There is no model
here, so there is no accuracy number, and `scripts/scorecard_report.py` opens by saying so
rather than leaving a gap that gets filled in later by someone in a hurry. What it prints
instead is the guard scored against all 30 frozen questions.

```
python3 scripts/scorecard_report.py --db /tmp/wh.duckdb --json /tmp/s.json
python3 scripts/scorecard_chart.py  --db /tmp/wh.duckdb --out docs/day7_scorecard.png
python3 -m tests.run_all            17 modules, 243 checks, 243 passed
```

**The pooled number, and how much of it is free.**

| arm | pooled, any refusal counts | out of 30 |
|---|---|---|
| refuse everything | 8 | 26.7 % |
| approve everything | 22 | 73.3 % |
| this repo | 27 | 90.0 % |

A system with no guardrails at all scores 73.3 percent, because the set holds 22 correct
queries against 8 that should be stopped and approving everything gets all 22. That floor
is measured rather than argued. It is `scorecard.open_guard` and it is one of the arms
above. Six days of guardrails moved the number by 5 questions.

**The two halves are not the same kind of evidence.** The 22 answerable questions are run
as their gold SQL, and that half is in sample by construction. Three checks fail the build
if any layer refuses a gold query, and day 4's first column rule refused six of them and
was rewritten. So the 22 record a green test rather than a measurement. The 8 refuse
questions are run as hand written plausible SQL and they are the only part that could have
gone badly.

| the out of sample half | |
|---|---|
| refused by something | 5 of 8 |
| refused by the layer its label points at | 4 of 8 |
| exact one sided 95 % lower bound on 5 of 8 | 0.289 |

Eight observations do not support a percentage. The bound is what the count licenses, and
it is the same Clopper Pearson convention used on the earlier project in this program, so
the two are comparable. `check_the_lower_bound_reproduces_two_figures_from_an_earlier_project`
pins it against two values computed independently in July.

**Take a layer away and score it again.** `guard.approve` grew a `layers` argument for
this and for nothing else. An empty set raises rather than approving, and a check walks
`agent/` with `ast` and fails if any call site there ever passes it.

| layers | pooled | refused, any | refused, matching | raised |
|---|---|---|---|---|
| all three | 27 | 5 of 8 | 4 of 8 | 0 |
| no cost | 27 | 5 of 8 | 4 of 8 | 0 |
| no validate | 26 | 4 of 8 | 4 of 8 | 1 |
| no gate | 27 | 5 of 8 | 1 of 8 | 0 |
| gate only | 25 | 3 of 8 | 3 of 8 | 0 |
| validate only | 27 | 5 of 8 | 1 of 8 | 0 |
| cost only | 23 | 1 of 8 | 1 of 8 | 4 |

**Removing the cost layer changes nothing.** A whole day of work and the frozen set cannot
see it. Day 5 said that in words. This is the number, and
`check_taking_the_cost_layer_away_changes_nothing_on_this_set` fails the suite if it ever
stops being true, which would mean this paragraph needs rewriting.

**Removing the parser gate also changes nothing, under the reading this repo quoted for
five days.** Static validation refuses a `DELETE` on its own, because `json_serialize_sql`
only serializes reads and everything else comes back as `unparseable`. Same score, wrong
reason. The gate's entire contribution is the reason, and the reason only shows up in the
matching reading. That is 4 of 8 with the gate and 1 of 8 without it. A repo quoting a
single number would have concluded the gate was redundant.

**The cost layer alone raises on four questions rather than refusing them.** `EXPLAIN` on
a `DELETE` over a read-only connection is an `InvalidInputException` and `EXPLAIN` on an
unknown column is a `BinderException`, and neither is caught. Day 5 put cost last because
`EXPLAIN` binds and binding a table function opens what it points at. This is the cruder
second reason. Run first it does not refuse, it explodes. A raised exception is counted
wrong on both halves throughout, because an ablation that scored a crash as coverage would
report the layer it just removed as unnecessary.

![the scorecard and the layer ablation](docs/day7_scorecard.png)

## What day 7 got wrong

**Day 6 printed the matching reading as `refused_by_something - 1`.** It was correct on
the day and it was arithmetic rather than a definition. `scorecard.OWNER` is the
definition now, and `check_the_matching_reading_is_not_refused_minus_one` uses a fixture
where the gap is two, so anything subtracting one fails. This is the `ot-037` class from
the day before, which is a published figure with nothing producing it.

**The `layers` argument is a way to turn the guard down.** Adding one on the last day, to
a module whose whole point is being the only door, is the kind of change that looks
harmless in a diff. It is closed as far as it can be closed. An empty set raises, an
unknown layer name raises, and nothing in `agent/` may pass it. The cost is stated in
`docs/adr-0011` rather than argued away.

**The check that the cost layer changes nothing passed whether or not the layer ran.** A
mutant making `layers` ignore its cost entry survived the suite, because the arm with the
layer and the arm without it score the same either way and that is the finding the check
was written about. It needed a query the cost layer does refuse, which is the day 5
inequality join. That is a ninth distinct way something has passed here while being wrong,
and it is the first where the reason was the result being reported.

**The first fix for the self join defect had the same defect in it.** See below.

## Two false refusals closed on day 7

`unrelated_join` refuses a join whose condition does not relate the two sides. It counted
distinct real **tables**, so every self join was refused, because both aliases resolve to
one table. That is `ot-035`, found on day 5 and left alone because the fix is a design
question rather than a patch. The unit is the qualifier and not the table, since what the
rule is asking is whether the condition relates two relations.

```sql
-- refused until today. It runs, and it is an ordinary repeat purchase question.
SELECT a.order_id, b.order_id
FROM retail.fct_order_header a
JOIN retail.fct_order_header b
  ON a.customer_id = b.customer_id AND a.order_id < b.order_id
```

**The first version of that fix still filtered the qualifiers through the catalog, and a
mutation pass found it.** A mutant removing the filter survived, and the reason it
survived is that the filter was a second false refusal of exactly the same kind. A join to
a CTE or to a derived table names a qualifier that is not a base table, so it did not
count as a side and the join was refused.

```sql
-- also refused until today. It runs and returns five rows.
WITH big AS (SELECT customer_id, count(*) AS n FROM retail.fct_order_header GROUP BY customer_id)
SELECT c.full_name, b.n FROM retail.dim_customer c
JOIN big b ON b.customer_id = c.customer_id ORDER BY b.n DESC LIMIT 5
```

No gold query self joins and no gold query joins a CTE, so the answer key check stayed
green through both. That is the third and fourth time a rule here has looked correct until
it met a shape the answer key does not contain, after the day 4 output alias and the day 5
bare count. Running a guardrail over the answer key is necessary and it is not sufficient.
Both fixes were reverted in a scratch copy and the new checks confirmed failing before
they were committed.

## Mutation, day 7

Twenty two mutants over `evals/scorecard.py`, the `layers` argument in `agent/guard.py`
and the join rule in `agent/validate.py`. The first round of twenty killed eighteen. Both
survivors were real gaps rather than unreachable branches, and one of them was a live
defect in that day's own fix. After the two fixes a second round of twenty two killed
everything, with the control clean.

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
rather than `refused`, and day 6 sends a different correction back for each.

**Eleven of the fourteen correction strategies have never met a real input.** They are
reachable, so this is not dead code. It is eleven untested decisions about what to tell a
model, and nothing in the eval set exercises any of them. Widening the eval set is the
honest fix and day 7 does not have room for it.

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
which is a different kind of act and belongs behind a decision rather than in a day 5
commit.

**The Snowflake path has never run.** `adapter.snowflake()` carries `verified = False` and
a test asserts it. Every number in this repo comes from DuckDB. `cost.read_plan` is written
against DuckDB's plan document and Snowflake returns a different one, so the cost layer does
not port either.

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
constraints is a day 1 change and it rebuilds the warehouse, which changes the gold answers
that every number since day 1 rests on. The freeze hash covers the questions and not the
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
second defect of the same kind. See the day 7 section.

## Mutation

The test suite is checked by breaking things on purpose. Day 1 ran 12 mutants and killed
11. Day 2 ran 14 more over the new modules and killed 13. Day 3 ran 14 more and killed 13.
Day 4 ran 17 and killed 15, then 14 more over the structural detector and killed 13. Day 5
ran 15 and killed 14. Day 6 ran 30 over two rounds and killed all of them after six fixes.
Day 7 ran 20 and killed 18, then 22 and killed all 22.

Every survivor across the week was either a deliberate control, an unreachable branch that
was kept for a stated reason, or a real gap that became a test. Two of them were live
defects in the code of the day that found them.
