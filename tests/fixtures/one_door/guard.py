"""Stands in for `agent/guard.py`. The detector skips this file by name.

The door is allowed to hold the only non literal `.execute()` in the package. That is
what makes it the door.
"""


def approve(con, sql):
    return True


def execute(con, sql):
    if not approve(con, sql):
        return None
    return con.execute(sql).fetchall()
