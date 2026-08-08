"""Which tables does a question actually need?

The eval set is frozen and every scored question carries gold SQL, so the answer is
already written down. It just has to be read out. A table is relevant to a question when
the gold query for that question reads from it.

The tables are pulled out of DuckDB's own parse tree rather than out of the query text.
Same reasoning as `warehouse/catalog.py` reading the catalog out of `information_schema`.
A regex over SQL gets aliases wrong, gets a CTE name confused with a real table, and gets
the word "from" inside a string literal. The parser that will run the query is the only
thing that knows what the query means.

`json_serialize_sql` walks the whole statement, so a table buried in a subquery inside a
HAVING clause is found the same as one in the top level FROM.
"""

import json


def _walk(node, tables, cte_names):
    if isinstance(node, dict):
        # a CTE is a name bound inside this statement, not a table in the warehouse
        cte_map = node.get("cte_map")
        if isinstance(cte_map, dict):
            for entry in cte_map.get("map", []):
                key = entry.get("key")
                if key:
                    cte_names.add(key.lower())
        if node.get("type") == "BASE_TABLE":
            tables.add((node.get("schema_name") or "", node.get("table_name")))
        for value in node.values():
            _walk(value, tables, cte_names)
    elif isinstance(node, list):
        for value in node:
            _walk(value, tables, cte_names)


def tables_in(con, sql):
    """Base tables read by `sql`, as lowercase bare names. CTE names are excluded."""
    raw = con.execute("SELECT json_serialize_sql(?)", [sql]).fetchone()[0]
    doc = json.loads(raw)
    if doc.get("error"):
        raise ValueError(
            "could not parse gold sql: %s" % doc.get("error_message", "unknown")
        )
    tables = set()
    cte_names = set()
    _walk(doc, tables, cte_names)
    return frozenset(
        name.lower() for _schema, name in tables if name.lower() not in cte_names
    )


def gold_relevance(con, rows):
    """{question id: frozenset of table names} for every question with gold SQL."""
    out = {}
    for row in rows:
        if not row.get("gold_sql"):
            continue
        needed = tables_in(con, row["gold_sql"])
        if not needed:
            raise ValueError("%s references no tables at all" % row["id"])
        out[row["id"]] = needed
    return out


def coverage(relevance, all_tables):
    """Tables the gold queries never touch.

    Worth printing rather than hiding. A table no question needs is a distractor for
    every question, and the retrieval numbers below are partly a measure of how well the
    scorer ignores it.
    """
    used = set()
    for needed in relevance.values():
        used |= needed
    return sorted(set(all_tables) - used)
