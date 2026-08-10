"""The same door as `one_door/guard.py`. Two modules beside it go round it."""


def approve(con, sql):
    return True


def execute(con, sql):
    if not approve(con, sql):
        return None
    return con.execute(sql).fetchall()
