"""A planted second door, and the shape it is most likely to arrive in.

Nobody adds `con.execute(model_sql)` on purpose. They add a helper that only wants the
plan, or only wants a row count, and it looks harmless because it is not running the
query for its answer. It is still model text reaching the connection.

The cost layer of this project is a cost ceiling, which needs exactly this call.
"""

import guard


def answer(con, sql):
    return guard.execute(con, sql)


def plan(con, sql):
    return con.execute("EXPLAIN " + sql).fetchall()  # DEFECT


def stub(con):
    """A placeholder nobody filled in.

    It is a constant and it is not a string, which is a different thing. The rule is
    that the argument must be a literal string, so this is reported. A mutation run
    found that the string half of that test was carrying no weight without this line.
    """
    return con.execute(...)  # DEFECT
