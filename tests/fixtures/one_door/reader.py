"""A module that behaves. Model SQL reaches the database through the door only.

The second function talks to the connection directly and is fine, because what it hands
over is a literal written here. A literal cannot be model output.
"""

import guard


def answer(con, sql):
    return guard.execute(con, sql)


def row_count(con):
    return con.execute("SELECT COUNT(*) FROM retail.fct_order_header").fetchone()[0]
