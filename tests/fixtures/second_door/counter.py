"""A second offender in a second file, so the report covers the whole directory.

The bare name is the obvious case. It sits beside the concatenation in `explainer.py`,
because a detector that finds one and stops is not much use.
"""


def rows(con, sql):
    return con.execute(sql).fetchall()  # DEFECT


def total(con):
    return con.execute("SELECT COUNT(*) FROM retail.dim_customer").fetchone()[0]


def prepared(con, sql):
    """The prepared statement shape. There is no argument at the call at all.

    The two defects in this file straddle line ten on purpose, so that sorting the
    report as text rather than by line number changes the answer.
    """
    stmt = con.prepare(sql)
    return stmt.execute()  # DEFECT
