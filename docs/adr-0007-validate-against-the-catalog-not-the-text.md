# ADR 0007: validate against the catalog, and treat an empty check as a failure

Date: 2026-08-10. Day 4.

## Context

Day 3 gated every query on `json_serialize_sql`. The rule was that a query must serialize
and must be exactly one statement. That refuses writes and stacked statements and `COPY`
and `EXPORT DATABASE`. It was written on the same day the probe measured that a read-only
connection allows `read_csv` on a host path.

The two never met. `SELECT * FROM read_csv('/etc/hostname')` is a single SELECT. It
serializes. It is one statement. The gate approves it and the read-only connection runs
it.

Measured today with `scripts/validation_report.py`:

```
read a host file as text   allows   ran, 1 rows, first cell '/etc/hostname'
list the filesystem        allows   ran, 95 rows, first cell '/etc/.pwd.lock'
```

The day 3 gate alone approves 14 of 17 probe queries. Twelve of those fourteen are things
no analytics agent should ever run.

## Why the obvious validator would not have caught it

The blueprint line for today is table and column existence plus an injection check. The
obvious build is to walk the base tables in the parse tree and check each against the
catalog.

A table function is not a base table. `read_csv(...)` parses to a `TABLE_FUNCTION` node.
A validator that iterates base tables finds an empty list and checks nothing, so it
reports no problem. The most dangerous query in the set is the one that gives the check
the least to do.

This program has now met that shape three times. `prose_check.py` printed clean while
looking at zero files. The day 3 gate approved a string of semicolons that parsed to zero
statements. Now this.

## Decision

Two things, and the second is the one worth remembering.

**Refuse every table function.** `ALLOWED_TABLE_FUNCTIONS` is empty. The warehouse is one
database file and nothing the agent is asked to do reads a path. Adding an entry later
means naming the function and the reason.

**Make "nothing to check" a finding.** `no_relation` fires when a query reads no table in
the warehouse. `SELECT 42` is refused. So is any future shape that reaches the validator
without giving it a subject.

Order is gate then validate, in `agent/guard.py`, which is now the only path from
generated SQL to the connection. `role.run` was deleted rather than left as a second door,
because `ot-026` is an open thread about exactly this and the fix for a rule a caller has
to remember is to remove the caller's choice. `tests/test_guard.py` walks `agent/` with
`ast` and fails if any `.execute()` outside `guard.py` is handed something that is not a
string literal.

## What this refuses that it should not, and how that was found

The first version of the column rule refused **6 of the 22 gold queries**. All six for the
same reason:

```sql
SELECT s.store_name, count(*) AS orders
FROM   retail.fct_order_header h
JOIN   retail.dim_store s ON s.store_id = h.store_id
GROUP  BY s.store_name
ORDER  BY orders DESC
```

`orders` is bound by the statement. It is not in the catalog and it never will be. A
guardrail that refuses more than a quarter of correct queries does not get tightened, it
gets switched off, and then it protects nothing. Output aliases are collected in the same
walk and a bare column matching one is skipped.

The check that caught this is `check_every_gold_query_validates_clean`. It exists because
the answer key is the one set of queries that must never be refused.

## What is deliberately not checked

- **Types.** `CAST(customer_email AS INTEGER)` passes both layers and fails at execution.
  The binder is better at types and the pipeline reports that outcome as `failed` rather
  than `refused`, which is the distinction day 6 needs.
- **Bare columns under a CTE or a subquery.** Those names can be bound inside the query,
  and resolving them properly means implementing name resolution. Guessing produces false
  refusals on correct SQL, which is the failure mode this ADR is about. The count of
  skipped references is reported rather than hidden. Over the answer key it is 112 checked
  and 8 skipped.
- **Whether a column may be read.** That is `ot-032` and no day of the blueprint carries
  it. `SELECT customer_email FROM retail.dim_customer` still passes everything here.

## Consequences

Refusal coverage on the frozen eval set goes from 3 of 8 to 4 of 8. The honest reading of
that number is in `scripts/validation_report.py`. q029 is also refused, by the cross join
rule, and it is labelled `unbounded_scan`. Counting it as cost coverage would be claiming
a day 5 result on day 4. q028 is the same category with no cross join in it and nothing
built so far touches it.

An approved query is parsed twice, once by `role.inspect` and once by `validate.check`.
Both trees could be built once and shared. That is not done yet because the two layers
are separable today and a shared tree couples them, and because the whole of approval is
0.571 ms per query against 1.1 ms to run one.

The first draft was worse than that. `pipeline.answer` called `approve` for its trace and
then called `execute`, which approved again, so every query was parsed four times.
`guard.execute` returns a `Result` carrying the verdict now and the pipeline calls it
once. The alternative was for `execute` to accept a verdict the caller had already
computed, which is the trust parameter `ot-026` warns about.
