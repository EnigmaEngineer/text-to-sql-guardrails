"""A module that calls nothing.

`called_attribute_names` is used to assert that a caller does reach for one module and
does not reach for another. The second half is the dangerous one. On a file with no
calls in it the absence holds for free, so every negative assertion passes and proves
nothing at all.
"""

SCHEMA = "retail"

TABLES = ("fct_order_header", "dim_customer")


def qualified(table):
    return SCHEMA + "." + table
