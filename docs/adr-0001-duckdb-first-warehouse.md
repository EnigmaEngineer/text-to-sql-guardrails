# ADR 0001: DuckDB is the verified warehouse, Snowflake is written alongside

Status: accepted

## Context

The project targets Snowflake. There is no Snowflake account. The cost layer has to estimate query
cost from `EXPLAIN` output and the write-up has to publish accuracy numbers, and both of those
are worthless if they were never executed anywhere.

Two bad options were available. Write Snowflake SQL and never run it, which produces a
repo full of untested strings. Or spend the first week acquiring and loading a trial
account, which spends the whole project on setup.

## Decision

Every measurement in this repo runs against DuckDB. `warehouse/adapter.py` holds a small
`Dialect` record per engine and the Snowflake one carries `verified = False`.

A test asserts that flag. If it ever flips to true without a real Snowflake run behind it,
every cost number the project publishes becomes unfounded, so the flag is worth a test.

## Consequences

Cost estimation is the part that suffers. DuckDB's `EXPLAIN` gives a plan and a row
estimate. Snowflake's `EXPLAIN USING JSON` gives bytes scanned and partition counts, which
is a different and better input to a spend ceiling. The cost layer will build the ceiling against
what DuckDB offers and the Snowflake mapping stays unverified.

The honest statement in the README is that the cost model was tuned on one engine and
ported to another on paper. That is weaker than a measured claim and it is what the
evidence supports.

The DuckDB file cannot live under the Projects folder while the sandbox builds it. A
checkpoint unlinks the write ahead log and the mount refuses unlink. The repo default
still points at `warehouse/retail.duckdb` because that path is correct on a laptop.
