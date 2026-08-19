"""Read the catalog out of the live database rather than out of the DDL text.

Parsing schema.sql would give a catalog that agrees with the file and can still disagree
with the database. Static validation has to answer "does this column exist", and the only answer that
is worth anything comes from the thing the query will actually run against.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Column:
    table: str
    name: str
    data_type: str
    nullable: bool


@dataclass(frozen=True)
class Table:
    schema: str
    name: str
    columns: tuple

    @property
    def qualified(self):
        return "%s.%s" % (self.schema, self.name)

    def render(self):
        cols = ", ".join("%s %s" % (c.name, c.data_type) for c in self.columns)
        return "%s(%s)" % (self.qualified, cols)


def read(con, schema="retail"):
    rows = con.execute(
        """
        SELECT table_name, column_name, data_type, is_nullable, ordinal_position
        FROM information_schema.columns
        WHERE table_schema = ?
        ORDER BY table_name, ordinal_position
        """,
        [schema],
    ).fetchall()
    if not rows:
        raise ValueError("no columns found in schema %r. Was the warehouse built?" % schema)

    by_table = {}
    for table_name, col, dtype, nullable, _pos in rows:
        by_table.setdefault(table_name, []).append(
            Column(table_name, col, dtype, nullable == "YES")
        )
    return tuple(
        Table(schema, name, tuple(cols)) for name, cols in sorted(by_table.items())
    )


def render_all(tables):
    """The whole schema as prompt text. The retrieval layer exists because this is too big to send."""
    return "\n".join(t.render() for t in tables)


def column_index(tables):
    """(table, column) pairs, lowercased. What a validator checks a name against."""
    return {
        (t.name.lower(), c.name.lower())
        for t in tables
        for c in t.columns
    }
