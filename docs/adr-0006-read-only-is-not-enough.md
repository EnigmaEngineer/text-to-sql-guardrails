# ADR 0006: The read-only role is the second layer, not the first

Status: accepted

## Context

The plan here is generation with a read-only role. The obvious reading is that
the connection gets opened with `read_only=True` and the safety question is answered.

It is not answered. `scripts/role_probe.py` runs every statement below against a
read-only copy of the warehouse. A statement that is refused is then retried against a
writable copy, so a refusal caused by a mistake in the probe is reported as invalid SQL
rather than counted as a protection.

Measured on duckdb 1.5.5.

| statement | read-only connection |
|---|---|
| INSERT, UPDATE, DELETE | blocked |
| CREATE, DROP, ALTER, CREATE VIEW | blocked |
| CREATE TEMP TABLE | allowed |
| SET memory_limit | allowed |
| `COPY (SELECT ...) TO 'file.csv'` | **allowed** |
| `EXPORT DATABASE 'dir'` | **allowed** |
| `SELECT ... FROM read_csv('/etc/hostname')` | **allowed** |
| `INSTALL httpfs` then `LOAD httpfs` | **allowed** |
| `SELECT 1; COPY (...) TO 'file.csv'` | **allowed** |

The read-only role protects the database. It has no opinion about anything that does not
write to the database, and moving data out of it is not a write to it.

Two of those rows are worth stating plainly. `EXPORT DATABASE` on a read-only connection
wrote 23 files and 208,969 rows to disk, including every customer email and every
employee row. And `con.execute` runs more than one statement, returning the result of the
last. So this single call, on a connection opened read-only, returned a row count and
left a file containing 4,000 customer email addresses:

```sql
SELECT 1 AS ok; COPY (SELECT customer_email FROM retail.dim_customer) TO '/tmp/x.csv'
```

Two of the eval set's eight refusal questions are tagged `pii_export`. The role that was
supposed to make the agent safe is the role under which that query succeeded.

## Decision

A gate runs before anything reaches the connection, and the read-only connection stays
behind it. Neither layer is trusted alone.

The gate asks DuckDB to serialize the SQL with `json_serialize_sql`. DuckDB only
serializes SELECT, so a COPY or an INSERT comes back as an error with `error_type` set to
`not implemented`. The parse also splits the string into statements the way the engine
will, so a semicolon inside a string literal does not count as a split.

Approval needs both of:

- the serializer succeeded, which means every statement in the string is a read
- there is exactly one statement

There are four refusal labels rather than one. They are `not_a_read` and
`multiple_statements` and `unparseable` and `empty`. The correction loop has to tell a
model what it did wrong and a single label cannot carry that.

Three things follow that are easy to get wrong.

**Node types are not allowlisted.** A `UNION` parses to `SET_OPERATION_NODE` rather than
`SELECT_NODE`. There is no `UNION` anywhere in the frozen eval set. An allowlist written
against it would reject a correct query the first time a question needed one, and it
would look like a guardrail working.

**Zero statements is a refusal.** A string of whitespace and semicolons serializes without
error into no statements at all. A gate that finds nothing wrong with nothing is the same
bug as a checker that reports clean having read no files.

**The read-only connection stays.** It is redundant while the gate is correct and it is
the thing that holds if the gate is ever wrong. `tests/test_role.py` pins the current
behaviour, so a future DuckDB that starts refusing COPY on a read-only connection breaks
a test rather than silently making this document stale.

## Consequences

The gate refuses three of the eight refusal questions in the eval set, all three tagged
`write_operation`, verified by running the obvious write SQL for each through the
pipeline. The other five are not reachable by anything built so far. One needs the column
checker, two need the cost ceiling, and two are `pii_export` and have
no layer designed for them at all.

That last gap is the honest cost of this decision. A `SELECT customer_email FROM
dim_customer` is a single read, it passes the gate cleanly, and it is exactly what
question q026 asks for. Nothing in this repo currently stops it. A column level policy is
the obvious answer and nothing in the plan asks for it, so it is carried as an open
thread rather than quietly added to a later day's line.

No accuracy number is claimed. There is no model in this environment, so generation
runs through a scripted fixture and the 22 of 22 in `scripts/generation_report.py` is a
statement about the plumbing.
