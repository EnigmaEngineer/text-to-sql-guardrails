"""The read-only role, and the gate that has to sit in front of it.

Opening the connection with `read_only=True` is the obvious move and it is not enough.
Measured on 2026-08-09 against duckdb 1.5.5 by `scripts/role_probe.py`, a read-only
connection still allows all of these:

    COPY (SELECT ...) TO '/tmp/x.csv'   wrote 4,000 customer emails to disk
    EXPORT DATABASE '/tmp/dump'         dumped the warehouse
    SELECT * FROM read_csv('/etc/...')  read a file off the host
    INSTALL httpfs / LOAD httpfs        loaded an extension that adds remote file sinks
    CREATE TEMP TABLE                   allowed, because temp tables are not the database

None of those write to the database, so the read-only role has no opinion about them.
The role protects the warehouse. It does not protect the data in it.

Worse, `con.execute` runs more than one statement and hands back the result of the last
one. So a single call of

    SELECT 1; COPY (SELECT customer_email FROM retail.dim_customer) TO '/tmp/x.csv'

returned a row count and left a file on disk, on a connection opened read-only.

So the gate below runs first and the read-only connection sits behind it. Two layers,
because either one alone has a hole the other covers.

The gate is DuckDB's own parser rather than a regex. `json_serialize_sql` refuses
anything that is not a SELECT, with `error_type` "not implemented", and it splits a
string into statements the way the engine will. A semicolon inside a string literal does
not split. That is the day 2 reasoning about `information_schema` arriving somewhere new.
Ask the engine what the query is, do not guess from the text.
"""

import json
from dataclasses import dataclass, field

# What `json_serialize_sql` says when it meets a statement it will not serialize. DuckDB
# only serializes SELECT, so this string is doing real work and not decoration.
NOT_A_SELECT = "not implemented"


class Refused(Exception):
    """Raised instead of running SQL the gate would not approve."""

    def __init__(self, decision):
        super().__init__("%s: %s" % (decision.reason, decision.detail))
        self.decision = decision


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    detail: str = ""
    statements: int = 0
    node_types: tuple = field(default_factory=tuple)

    def as_dict(self):
        """For the trace. Day 6 wants every decision the agent made, not just the last."""
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "detail": self.detail,
            "statements": self.statements,
            "node_types": list(self.node_types),
        }


def connect(db_path):
    """A read-only connection. The second layer, never the only one."""
    import duckdb

    return duckdb.connect(db_path, read_only=True)


def inspect(con, sql):
    """Decide whether `sql` is a single read that the agent is allowed to run.

    Four ways to be refused, and they are kept apart because day 6 has to tell a model
    what it did wrong. "Your query was rejected" does not help it self correct.
    """
    if sql is None or not sql.strip():
        return Decision(False, "empty", "no SQL was supplied")

    raw = con.execute("SELECT json_serialize_sql(?)", [sql]).fetchone()[0]
    parsed = json.loads(raw)

    if parsed.get("error"):
        kind = parsed.get("error_type", "")
        message = parsed.get("error_message", "").strip()
        if kind == NOT_A_SELECT:
            return Decision(False, "not_a_read", message)
        return Decision(False, "unparseable", message)

    statements = parsed.get("statements", [])
    node_types = tuple(s.get("node", {}).get("type", "?") for s in statements)

    # A string of only whitespace and semicolons parses cleanly into nothing at all, and
    # a gate that says nothing is wrong with zero statements is the 08-04 prose_check bug
    # wearing a different hat. Count first, then judge.
    if len(statements) == 0:
        return Decision(False, "empty", "parsed to zero statements", 0, node_types)
    if len(statements) > 1:
        return Decision(
            False,
            "multiple_statements",
            "%d statements in one string" % len(statements),
            len(statements),
            node_types,
        )

    return Decision(True, "single_read", "", 1, node_types)


# There used to be a `run` here that gated and then executed. It was removed on day 4.
# It was a second way into the database that knew about the parser and not about the
# catalog, so `agent.validate` would have had to be added in two places and one of them
# would eventually have been missed. `agent.guard.execute` is the only door now.
