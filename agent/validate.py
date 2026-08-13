"""Static validation of generated SQL against the catalog the query will run on.

Day 3 built a gate that asks DuckDB's parser whether a string is one read. That gate
approves this:

    SELECT * FROM read_csv('/etc/hostname')
    SELECT * FROM glob('/etc/*')

Both are a single SELECT, so both serialize cleanly and both run. Measured on
2026-08-10, `glob('/etc/*')` returned 95 rows and `read_text('/etc/hostname')` returned
the contents of the file. The day 3 probe had already recorded that a read-only
connection allows `read_csv` on a host path. The gate written the same day was never
pointed at it, so the finding and the control never met.

The reason a table function slips through is worth stating, because it decides the shape
of this module. A table function is not a BASE_TABLE in the parse tree. It is a
TABLE_FUNCTION node. So a validator that walks the base tables and checks each one
against the catalog finds nothing to check and reports no problem. That is a check
passing on zero inputs, which is the third time this program has met that shape, after
`prose_check.py` reporting clean on an empty file list and the day 3 gate approving a
string of semicolons that parsed to zero statements.

So `no_relation` is a finding here rather than a silence. A query the agent produces is
supposed to read the warehouse. One that reads nothing in the warehouse is either a
probe or a hallucination and neither should reach the connection.

What this module does not do:

- It does not check types. `WHERE order_id = 'abc'` is a binder problem and the binder
  is better at it.
- It does not judge whether the query answers the question. That is the eval set's job.
- It does not resolve names through a derived table. See `_columns` for where it stops
  and why it stops there rather than guessing.
"""

import json
from dataclasses import dataclass, field

# Every table function is refused. There is no allowlist entry because the warehouse is
# a single database file and nothing the agent is asked to do needs to read a path.
# Adding one later means naming the function and the reason, which is the point of
# keeping the set here rather than in a condition.
ALLOWED_TABLE_FUNCTIONS = frozenset()


@dataclass(frozen=True)
class Finding:
    code: str
    detail: str

    def __str__(self):
        return "%s: %s" % (self.code, self.detail)


@dataclass(frozen=True)
class Report:
    ok: bool
    findings: tuple = ()
    tables: frozenset = frozenset()
    checked_columns: int = 0
    skipped_columns: int = 0

    def codes(self):
        return tuple(f.code for f in self.findings)

    def as_dict(self):
        """For the trace. Day 6 wants the reason, not a boolean."""
        return {
            "ok": self.ok,
            "findings": [{"code": f.code, "detail": f.detail} for f in self.findings],
            "tables": sorted(self.tables),
            "checked_columns": self.checked_columns,
            "skipped_columns": self.skipped_columns,
        }


@dataclass
class _Shape:
    """What one statement refers to. Collected in a single walk of the parse tree."""

    base_tables: list = field(default_factory=list)   # (schema, name, alias)
    table_functions: list = field(default_factory=list)  # (function_name, alias)
    column_refs: list = field(default_factory=list)   # tuple of name parts
    cte_names: set = field(default_factory=set)
    joins: list = field(default_factory=list)
    has_subquery: bool = False
    # Names the statement binds itself. `count(*) AS orders` puts `orders` here, and
    # `ORDER BY orders` then refers to it. Six of the 22 gold queries do exactly that,
    # so without this the validator refuses more than a quarter of the answer key.
    output_aliases: set = field(default_factory=set)


def _walk(node, shape):
    if isinstance(node, dict):
        cte_map = node.get("cte_map")
        if isinstance(cte_map, dict):
            for entry in cte_map.get("map", []):
                key = entry.get("key")
                if key:
                    shape.cte_names.add(key.lower())

        kind = node.get("type")
        # An alias on anything that is not a relation is an output name. Relations are
        # excluded because a table alias is a qualifier and belongs in `by_name`.
        if kind not in ("BASE_TABLE", "TABLE_FUNCTION", "SUBQUERY", "JOIN"):
            alias = node.get("alias")
            if isinstance(alias, str) and alias:
                shape.output_aliases.add(alias.lower())

        if kind == "BASE_TABLE":
            shape.base_tables.append(
                (
                    (node.get("schema_name") or "").lower(),
                    (node.get("table_name") or "").lower(),
                    (node.get("alias") or "").lower(),
                )
            )
        elif kind == "TABLE_FUNCTION":
            fn = node.get("function") or {}
            shape.table_functions.append(
                ((fn.get("function_name") or "?").lower(), (node.get("alias") or "").lower())
            )
        elif kind == "COLUMN_REF":
            parts = node.get("column_names") or []
            if parts:
                shape.column_refs.append(tuple(p.lower() for p in parts))
        elif kind == "JOIN":
            shape.joins.append(node)
        elif kind == "SUBQUERY":
            shape.has_subquery = True

        for value in node.values():
            _walk(value, shape)
    elif isinstance(node, list):
        for value in node:
            _walk(value, shape)


def shape_of(con, sql):
    """Parse `sql` and collect what it refers to. Raises if it will not parse.

    Callers reach this through `check`. It is separate so a report script can show the
    shape without pretending to judge it.
    """
    raw = con.execute("SELECT json_serialize_sql(?)", [sql]).fetchone()[0]
    doc = json.loads(raw)
    if doc.get("error"):
        raise ValueError(doc.get("error_message", "unparseable"))
    shape = _Shape()
    _walk(doc, shape)
    return shape


def _real_tables(shape):
    """Base tables that are not CTE references, keyed by every name they answer to."""
    by_name = {}
    real = []
    for schema, name, alias in shape.base_tables:
        if name in shape.cte_names:
            continue
        real.append((schema, name))
        by_name[name] = name
        if alias:
            by_name[alias] = name
    return real, by_name


def _columns(shape, by_name, known_columns, findings):
    """Check column references that can be attributed to a real table.

    Two cases are skipped rather than guessed at, and the count of skips is reported so
    a caller can see how much of the query went unchecked.

    A qualifier that is not a base table alias belongs to a CTE or a derived table, and
    its columns are bound inside the query rather than in the catalog. A bare column in
    a query that has a CTE or a subquery could have come from either, and resolving that
    properly means implementing name resolution, which is the binder's job and not this
    module's. Guessing here would produce false refusals on correct SQL, which is worse
    than a gap, because a guardrail that blocks good queries gets turned off.
    """
    checked = skipped = 0
    bare_ok = not shape.cte_names and not shape.has_subquery
    tables_in_play = sorted(set(by_name.values()))

    for parts in shape.column_refs:
        if len(parts) >= 2:
            qualifier, column = parts[-2], parts[-1]
            table = by_name.get(qualifier)
            if table is None:
                if bare_ok:
                    # No CTE and no subquery, so there is nothing in this statement that
                    # could bind `zz` in `zz.date_key`. Skipping it was safe while the
                    # join rule counted real tables, because a condition naming an
                    # unknown qualifier came out under two and was refused there. Day 7
                    # made the join rule count qualifiers, which is right, and that made
                    # this skip reachable from a query the guard then approved and the
                    # cost layer crashed on. Reported as `unknown_table` rather than as a
                    # new code, because that is what it is and a new code would need a
                    # correction strategy for a case no eval question reaches.
                    findings.append(
                        Finding(
                            "unknown_table",
                            "%s is not a relation this query defines" % qualifier,
                        )
                    )
                skipped += 1
                continue
            checked += 1
            if (table, column) not in known_columns:
                findings.append(
                    Finding("unknown_column", "%s.%s is not in the catalog" % (table, column))
                )
        else:
            column = parts[0]
            if column in shape.output_aliases:
                # `SELECT count(*) AS orders ... ORDER BY orders`. The name is bound by
                # this statement. Counted as skipped rather than checked, because
                # nothing about the catalog was consulted.
                skipped += 1
                continue
            if not bare_ok or not tables_in_play:
                skipped += 1
                continue
            checked += 1
            if not any((t, column) in known_columns for t in tables_in_play):
                findings.append(
                    Finding(
                        "unknown_column",
                        "%s is not a column of %s" % (column, " or ".join(tables_in_play)),
                    )
                )
    return checked, skipped


def _join_sides(node, by_name):
    """Which relation names a join condition mentions, counting aliases separately.

    This counted distinct real **tables** until day 7 and that refused every self join.
    `fct_order_header a JOIN fct_order_header b ON a.customer_id = b.customer_id AND
    a.order_id < b.order_id` is a repeat purchase question. Both aliases resolve to one
    table, so the old set had size one and the rule fired. No gold query self joins, so
    the answer key check stayed green while it shipped, which is the third time a rule
    here looked correct until it met a shape the answer key does not contain.

    Counting the qualifier is the right unit, because what the rule is actually asking is
    whether the condition relates the two sides of the join, and the sides are relations
    rather than tables.

    The first version of this fix kept a filter on `by_name`, so a qualifier belonging to
    a CTE or a derived table did not count as a side. A mutation pass removed the filter,
    survived, and the reason it survived is that the filter was a second false refusal of
    exactly the ot-035 kind. `... FROM dim_customer c JOIN big b ON b.customer_id =
    c.customer_id` with `big` a CTE was refused, and it is ordinary SQL that runs and
    returns rows. No gold query joins a CTE, so the answer key check stayed green through
    that too. Every qualifier counts now. A qualifier naming nothing real is somebody
    else's finding, `unknown_column` or the binder, and it is not this rule's business.

    `by_name` is still taken as an argument because the caller has it and a later version
    of this rule will want it. It is deliberately unused here rather than dropped, so the
    signature does not churn.
    """
    sub = _Shape()
    _walk(node.get("condition"), sub)
    return {parts[-2] for parts in sub.column_refs if len(parts) >= 2}


def _joins(shape, by_name, findings):
    for node in shape.joins:
        ref_type = (node.get("ref_type") or "").upper()
        if ref_type == "CROSS":
            # Both `a, b` and an explicit CROSS JOIN land here. Neither carries a
            # condition. The detail is what keeps them apart from a join that lost its
            # ON clause, and day 6 needs that difference to tell a model what to change.
            # The tests assert the detail rather than the code. A mutant that deleted
            # this branch survived a test that only read the code.
            findings.append(
                Finding("cross_join", "explicit cross join over warehouse tables")
            )
            continue
        if ref_type in ("NATURAL", "POSITIONAL"):
            # A natural join picks its own keys from whatever names happen to match, so
            # adding a column to a table silently changes the result. Not a security
            # problem, a correctness one, and cheap to refuse.
            findings.append(Finding("implicit_join", "%s join, name the keys" % ref_type.lower()))
            continue
        if node.get("using_columns"):
            continue
        # There was a branch here for a join with no condition. A mutant that deleted it
        # survived, and checking why showed it is unreachable. `a JOIN b` with no ON and
        # no USING is a syntax error, and the shapes that legitimately have no condition
        # are CROSS and NATURAL, both handled above. If some future ref_type arrives with
        # no condition, `_join_tables` returns an empty set and the rule below refuses it
        # anyway, so removing the branch costs no safety.
        related = _join_sides(node, by_name)
        if len(related) < 2:
            findings.append(
                Finding(
                    "unrelated_join",
                    "join condition touches %d relation(s), so the join does not relate "
                    "its sides" % len(related),
                )
            )


def check(con, tables, sql):
    """Validate `sql` against `tables`, the catalog read from the live database.

    Returns a `Report`. Never raises for bad SQL. A string that will not parse comes
    back as an `unparseable` finding, because the gate that runs before this one already
    refuses those and a second exception path would just be noise.
    """
    known_columns = {
        (t.name.lower(), c.name.lower()) for t in tables for c in t.columns
    }
    known_tables = {t.name.lower() for t in tables}

    try:
        shape = shape_of(con, sql)
    except ValueError as exc:
        return Report(False, (Finding("unparseable", str(exc)),))

    findings = []

    for fn_name, _alias in shape.table_functions:
        if fn_name not in ALLOWED_TABLE_FUNCTIONS:
            findings.append(
                Finding("table_function", "%s() reads outside the catalog" % fn_name)
            )

    real, by_name = _real_tables(shape)
    for _schema, name in real:
        if name not in known_tables:
            findings.append(Finding("unknown_table", "%s is not a table in the catalog" % name))

    if not real and not shape.table_functions:
        findings.append(Finding("no_relation", "query reads no table in the warehouse"))

    checked, skipped = _columns(shape, by_name, known_columns, findings)
    _joins(shape, by_name, findings)

    return Report(
        ok=not findings,
        findings=tuple(findings),
        tables=frozenset(name for _schema, name in real),
        checked_columns=checked,
        skipped_columns=skipped,
    )
