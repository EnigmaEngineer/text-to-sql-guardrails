"""Join edges, inferred from column naming. There are no foreign keys to read.

`schema.sql` declares primary keys and not one foreign key, so `duckdb_constraints()`
has nothing to hand over. The edges have to be guessed, and the guess used here is the
convention the schema happens to follow. A table whose primary key is `<x>_id` is
reachable from any table carrying a column called `<x>_id`.

This is inference and it is labelled as inference. `edge_agreement` measures it against
the joins the gold queries actually write, which is the only check available.

The layer exists because of a measurement, not because a graph seemed like a good idea.
Six of the twenty two questions need `dim_date` and not one of them contains the word
date. No scorer that reads the question and the table text can find that table, because
the question and the table share no vocabulary. It is reachable only through the table
next to it.
"""

from retrieval import relevance


def primary_keys(con, schema="retail"):
    """{table: pk column} for single column integer keys. Composite keys are skipped."""
    rows = con.execute(
        """
        SELECT table_name, constraint_text
        FROM duckdb_constraints()
        WHERE schema_name = ? AND constraint_type = 'PRIMARY KEY'
        """,
        [schema],
    ).fetchall()
    out = {}
    for table, text in rows:
        inner = text[text.find("(") + 1 : text.rfind(")")]
        cols = [c.strip() for c in inner.split(",")]
        if len(cols) == 1:
            out[table] = cols[0]
    return out


def edges(tables, pks):
    """{table: set of tables reachable in one join}. Undirected.

    A table is linked to another when it carries a column that is the other's primary
    key. The bridge table links this way to both sides without either declaring it.
    """
    by_name = {t.name: {c.name for c in t.columns} for t in tables}
    out = {name: set() for name in by_name}
    for name, cols in by_name.items():
        for other, pk in pks.items():
            if other == name:
                continue
            if pk in cols:
                out[name].add(other)
                out[other].add(name)
    return out


def expand(selected, links, hops=1):
    """Grow a set of tables by following join edges."""
    out = set(selected)
    frontier = set(selected)
    for _ in range(hops):
        nxt = set()
        for name in frontier:
            nxt |= links.get(name, set())
        nxt -= out
        if not nxt:
            break
        out |= nxt
        frontier = nxt
    return out


def gold_edges(con, rows):
    """Pairs of tables that appear together in one gold query.

    Not the same thing as a join. Two tables in one query might be joined to each other
    or might both be joined to a third. It is an upper bound on the real edge set and it
    is the cheap check, so the number it produces is named for what it is.
    """
    pairs = set()
    for row in rows:
        if not row.get("gold_sql"):
            continue
        used = sorted(relevance.tables_in(con, row["gold_sql"]))
        for i, a in enumerate(used):
            for b in used[i + 1 :]:
                pairs.add((a, b))
    return pairs


def edge_agreement(links, pairs):
    """How many co-occurring gold pairs the inferred graph connects within one hop."""
    hit = sum(1 for a, b in pairs if b in links.get(a, set()))
    return hit, len(pairs)
