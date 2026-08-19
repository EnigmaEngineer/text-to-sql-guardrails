# ADR 0009: the cost ceiling reads the largest step, not the sum of the scans

Status: accepted.

## Context

The next piece is cost estimation via `EXPLAIN` with a configurable
ceiling. `EXPLAIN (FORMAT JSON)` on duckdb 1.5.5 returns a plan tree where most nodes
carry an `Estimated Cardinality`. Something has to be turned into a number and compared
against a limit. Three candidates were on the table.

## What was measured

**Rows returned to the caller is not available.** Over the 22 answerable gold queries the
root node carries no estimate at all on 9 of them and reports exactly 0 on another 11,
against real answers of 4, 12 and 20 rows. Two carry a real number. So the most natural
ceiling, on how much comes back, cannot be built from this plan at all.

**Summing the scan nodes does not separate anything.** The query this layer exists for is
a join whose condition names two real tables, so static validation approves it cleanly:

```sql
SELECT count(*) FROM retail.fct_order_line l
JOIN retail.fct_web_session s ON l.quantity > s.page_views
```

Its scans sum to 104,357 against an answer key worst case of 70,523. A factor of 1.48.
No ceiling lives in that gap.

**The largest estimate on any node does separate.** The same query plans a
`PIECEWISE_MERGE_JOIN` estimated at 223,844,302 rows, against an answer key worst case of
64,357. A factor of 3,478.

The losing side was built out of the same plan reader rather than described, per the
08-01 rule. Both numbers above come from one walk of one plan.

## Decision

The ceiling reads `peak_rows`, the largest estimate on any node in the plan. It is
compared against the sum of `duckdb_tables().estimated_size` across the schema, which is
208,969 on this warehouse and 3.2x the answer key worst case.

The ceiling comes off the warehouse rather than out of the eval set on purpose. The
argument is that no question anyone types should make the engine handle more rows than
the warehouse holds. That reason survives a follow up question. Picking a number that
sits in a measured gap between the answer key and the attacks does not, and I
has already refused to do that once, on 08-06.

A plan carrying an operator with no estimate is refused rather than scored. The safe list
is derived from the answer key, not written from memory. See below.

**The obvious objection to the default, answered.** A ceiling that is the warehouse row
count scales with the warehouse. On a system holding a billion rows it sits at a billion
and effectively never fires. That is true and it is the right criticism. The default is
the honest one for a warehouse this size, where it lands at 3.2x the answer key and I can
show where the number came from. On a real system this is a service level decision rather
than a schema property, and it should be a number someone chose with a latency budget in
front of them. That is why the ceiling is a parameter and the derived value is only a
default.

## What this costs, stated plainly

**It buys no coverage on the eval set.** Two questions are tagged `unbounded_scan`. q029
was already refused by the cross join rule. q028 asks for every row of
`fct_web_session`, which the plan estimates at 40,000. q009 is a real analytical question
that reads the same table with no filter, and it estimates at 40,000 too. Their plans are
the same cost. No ceiling can separate them, because the difference between them is what
comes back to the user and that is the number the plan will not give. Refusal coverage
stays at 4 of 8.

**The estimate is not an upper bound.** Against DuckDB's own profiler, the estimate came
in below what the query really scanned on 8 of the 22 gold queries, worst at 0.23 of
actual. So this refuses the obvious accident and can be walked under by anything the
optimizer underestimates. It is not a defence against someone trying.

## Two things the first draft got wrong

Both are recorded because both are the same mistake in different clothes, which is that a
rule looks correct until it meets an input the answer key does not contain.

**The unscored operator list was written from memory and measured wrong on both halves.**
It named `CROSS_PRODUCT` and `NESTED_LOOP_JOIN`. A `NESTED_LOOP_JOIN` does carry an
estimate, so that entry could never have fired. And a join on a function of both sides
plans as `BLOCKWISE_NL_JOIN`, which carries none and was not in the list. The list is now
inverted and derived from the four operators that appear with no estimate across the
answer key. Anything else with no estimate is refused. The cost is a false
refusal on an unfamiliar but harmless operator, which is the direction to fail in and
shows up as a refusal someone can read.

The four are `ORDER_BY` and `UNGROUPED_AGGREGATE` and `PERFECT_HASH_GROUP_BY` and
`TOP_N`. Every one of them reduces or preserves row count.

**"No base table scan in the plan" refused a correct query.** `SELECT count(*) FROM
retail.dim_store` plans as a single `COLUMN_DATA_SCAN` with an estimate of 1, because
DuckDB answers it from table metadata and never touches the table. No gold question is a
bare count on one table, so the answer key check came back clean while this was live.
Refusing a query for reading no table is `agent.validate`'s job and it has `no_relation`
for it. The rule here is now that no node carrying a number is a finding.

## Where the layer sits, and why last

`EXPLAIN` is not a dry run. It binds the query, and binding a table function opens what
the function points at. `EXPLAIN (FORMAT JSON) SELECT * FROM read_csv('/tmp/probe.csv')`
returns `Projections: ["a", "b"]`, which are the column names out of the file. Point it at
a path that does not exist and it raises `IOException: No files found`.

So a cost layer placed first, on the reasonable sounding argument that the cheap check
should run before the expensive one, hands an attacker the filesystem read that
`agent.validate` exists to remove. Cost runs on a query two layers have already approved.
`tests/test_cost.py` pins both halves, the ordering and the fact that reaching it would
have hurt.

## Consequences

- One more refusal reason for the correction loop to feed back to a model, and it is actionable. Over
  the ceiling means add a filter. Unscored operator means name your join keys.
- `agent.guard.plan_of` is a second `.execute()` of model text and it lives behind the
  same door as the first. The structural check refused an earlier draft that built
  eighteen `count(*)` statements by string formatting, and it was right to.
- The Snowflake prefix stays in `warehouse/adapter.py` and is still unverified. Snowflake
  returns a different plan document, so `cost.read_plan` is written against DuckDB's shape
  and would need a second reader. Left as a named next step.
