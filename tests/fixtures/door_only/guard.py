"""A package holding nothing but the door.

The detector skips the door by name, so it reads zero files here and has no grounds to
report anything. It must say that rather than return an empty list.
"""


def execute(con, sql):
    return con.execute(sql).fetchall()
