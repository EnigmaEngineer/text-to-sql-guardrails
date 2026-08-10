"""Checks on static validation.

The fixture rule from 2026-08-02 applies here more than anywhere else in this repo. A
validator tested only on queries with one table cannot test any rule about how two
tables relate, so the join checks below use real joins over real tables rather than a
hand built shape.

Every check that asserts a refusal also asserts the code, not just that something was
found. A validator that refuses everything for the wrong reason passes a test that only
looks at `ok`.
"""

from agent import validate
from tests.harness import eq, true
from warehouse import catalog


def _tables(ctx):
    return catalog.read(ctx.con)


def check_a_gold_query_is_clean(ctx):
    tables = _tables(ctx)
    sql = (
        "SELECT c.city, COUNT(*) AS n "
        "FROM retail.dim_customer c "
        "JOIN retail.fct_order_header o ON c.customer_id = o.customer_id "
        "GROUP BY c.city ORDER BY n DESC"
    )
    r = validate.check(ctx.con, tables, sql)
    true(r.ok, "clean join query: %s" % (r.codes(),))
    eq(r.tables, frozenset({"dim_customer", "fct_order_header"}), "tables found")
    true(r.checked_columns >= 3, "checked some columns, got %d" % r.checked_columns)


def check_an_output_alias_in_order_by_is_not_an_unknown_column(ctx):
    """The false refusal that would have killed this feature.

    The first version of the column rule refused 6 of the 22 gold queries, all of them
    for the same reason. `count(*) AS orders` followed by `ORDER BY orders` is a name
    the statement binds itself and it is not in the catalog. A guardrail that refuses
    more than a quarter of correct queries does not get tightened, it gets switched off.
    """
    sql = (
        "SELECT s.store_name, count(*) AS orders "
        "FROM retail.fct_order_header h JOIN retail.dim_store s ON s.store_id = h.store_id "
        "GROUP BY s.store_name ORDER BY orders DESC"
    )
    r = validate.check(ctx.con, _tables(ctx), sql)
    true(r.ok, "alias in ORDER BY: %s" % (r.codes(),))
    # And the alias must not have been counted as a column that was verified.
    true(r.skipped_columns >= 1, "the alias was skipped, got %d" % r.skipped_columns)


def check_an_alias_does_not_launder_a_bad_column(ctx):
    """`AS orders` binds `orders`. It does not make `nope` acceptable."""
    sql = (
        "SELECT count(*) AS orders, nope FROM retail.fct_order_header ORDER BY orders"
    )
    r = validate.check(ctx.con, _tables(ctx), sql)
    true("unknown_column" in r.codes(), "codes %s" % (r.codes(),))


def check_every_gold_query_validates_clean(ctx):
    """If the validator refuses the answer key, the validator is wrong.

    This is the check that decides whether the column rules are usable at all. It ran
    red the first time and the rule that was too strict got narrowed rather than the
    query that tripped it getting special cased.
    """
    from evals import gold

    tables = _tables(ctx)
    rows = gold.answerable()
    eq(len(rows), 22, "22 answerable questions")
    bad = []
    for row in rows:
        r = validate.check(ctx.con, tables, row["gold_sql"])
        if not r.ok:
            bad.append((row["id"], r.codes()))
    eq(bad, [], "gold queries with findings")


def check_unknown_table_is_caught(ctx):
    r = validate.check(ctx.con, _tables(ctx), "SELECT * FROM retail.fct_nope")
    true("unknown_table" in r.codes(), "codes %s" % (r.codes(),))


def check_unknown_column_is_caught_when_qualified(ctx):
    sql = "SELECT c.not_a_column FROM retail.dim_customer c"
    r = validate.check(ctx.con, _tables(ctx), sql)
    true("unknown_column" in r.codes(), "codes %s" % (r.codes(),))


def check_unknown_column_is_caught_when_bare(ctx):
    sql = "SELECT not_a_column FROM retail.dim_customer"
    r = validate.check(ctx.con, _tables(ctx), sql)
    true("unknown_column" in r.codes(), "codes %s" % (r.codes(),))


def check_a_bare_column_from_the_other_side_of_a_join_is_fine(ctx):
    """The rule is "exists in some table in play", not "exists in the first table"."""
    sql = (
        "SELECT order_status FROM retail.dim_customer c "
        "JOIN retail.fct_order_header o ON c.customer_id = o.customer_id"
    )
    r = validate.check(ctx.con, _tables(ctx), sql)
    true(r.ok, "order_status belongs to the joined table: %s" % (r.codes(),))


def check_columns_are_skipped_rather_than_guessed_under_a_cte(ctx):
    """A CTE binds names this module cannot see, so bare columns go unchecked.

    `order_total_usd` below is deliberately not a column of anything. The point of the
    check is that it comes back clean, which proves the rule really is skipping rather
    than happening to agree. Asserting the skip count as well means a later change that
    switched the rule off entirely would not slip through on `ok` alone.
    """
    sql = (
        "WITH recent AS (SELECT order_id, order_total_usd FROM retail.fct_order_header) "
        "SELECT order_id FROM recent"
    )
    r = validate.check(ctx.con, _tables(ctx), sql)
    true(r.ok, "no findings: %s" % (r.codes(),))
    true(r.skipped_columns > 0, "skips are counted, got %d" % r.skipped_columns)


def check_a_derived_table_alias_is_not_reported_as_unknown(ctx):
    sql = (
        "SELECT s.oid FROM (SELECT order_id AS oid FROM retail.fct_order_header) s"
    )
    r = validate.check(ctx.con, _tables(ctx), sql)
    true(r.ok, "derived alias is skipped, not refused: %s" % (r.codes(),))


def check_table_function_is_refused(ctx):
    """The one the day 3 gate approves and runs."""
    tables = _tables(ctx)
    for sql in (
        "SELECT * FROM read_csv('/etc/hostname')",
        "SELECT * FROM glob('/etc/*')",
        "SELECT * FROM read_text('/etc/hostname')",
    ):
        r = validate.check(ctx.con, tables, sql)
        true("table_function" in r.codes(), "%r gave %s" % (sql, r.codes()))


def check_a_table_function_hidden_in_a_subquery_is_still_caught(ctx):
    """A regex on the FROM clause would miss this. The parse tree does not."""
    sql = (
        "SELECT customer_id FROM retail.dim_customer "
        "WHERE customer_id IN (SELECT 1 FROM glob('/etc/*'))"
    )
    r = validate.check(ctx.con, _tables(ctx), sql)
    true("table_function" in r.codes(), "codes %s" % (r.codes(),))


def check_a_query_reading_no_table_is_refused(ctx):
    """The vacuous pass, made loud.

    `SELECT 42` refers to nothing, so every name check has nothing to check and reports
    nothing wrong. Third time this program has met a check that passes on zero inputs.
    """
    r = validate.check(ctx.con, _tables(ctx), "SELECT 42")
    eq(r.codes(), ("no_relation",), "codes")


def check_cross_join_is_refused(ctx):
    """Asserts the detail, not just the code.

    Two branches in `_joins` produce `cross_join`, one for an explicit cross join and one
    for a join that lost its condition. A mutant that deleted the first survived a
    version of this check that only read the code, because the second caught it and the
    test could not tell them apart. That is the 08-02 rule about asserting the message.
    """
    for sql in (
        "SELECT COUNT(*) FROM retail.fct_order_line a, retail.fct_web_session b",
        "SELECT COUNT(*) FROM retail.fct_order_line CROSS JOIN retail.fct_web_session",
    ):
        r = validate.check(ctx.con, _tables(ctx), sql)
        eq(r.codes(), ("cross_join",), "codes for %r" % sql)
        eq(r.findings[0].detail, "explicit cross join over warehouse tables",
           "detail names the cross join branch")


def check_natural_join_is_refused(ctx):
    sql = "SELECT 1 FROM retail.dim_customer NATURAL JOIN retail.fct_order_header"
    r = validate.check(ctx.con, _tables(ctx), sql)
    true("implicit_join" in r.codes(), "codes %s" % (r.codes(),))


def check_a_join_condition_that_does_not_relate_its_sides_is_caught(ctx):
    """The join runs and returns a cartesian product wearing an ON clause."""
    sql = (
        "SELECT COUNT(*) FROM retail.dim_customer c "
        "JOIN retail.fct_order_header o ON c.customer_id = c.customer_id"
    )
    r = validate.check(ctx.con, _tables(ctx), sql)
    true("unrelated_join" in r.codes(), "codes %s" % (r.codes(),))


def check_using_is_accepted(ctx):
    sql = (
        "SELECT COUNT(*) FROM retail.dim_customer "
        "JOIN retail.fct_order_header USING (customer_id)"
    )
    r = validate.check(ctx.con, _tables(ctx), sql)
    true(r.ok, "USING names the key: %s" % (r.codes(),))


def check_a_cte_name_is_not_reported_as_an_unknown_table(ctx):
    sql = (
        "WITH t AS (SELECT order_id FROM retail.fct_order_header) "
        "SELECT t.order_id FROM t"
    )
    r = validate.check(ctx.con, _tables(ctx), sql)
    true("unknown_table" not in r.codes(), "codes %s" % (r.codes(),))


def check_unparseable_sql_comes_back_as_a_finding_not_an_exception(ctx):
    r = validate.check(ctx.con, _tables(ctx), "SELECT FROM WHERE")
    eq(r.codes(), ("unparseable",), "codes")
    eq(r.ok, False, "not ok")


def check_report_serialises_for_the_trace(ctx):
    import json

    r = validate.check(ctx.con, _tables(ctx), "SELECT 42")
    payload = json.loads(json.dumps(r.as_dict()))
    eq(
        sorted(payload),
        ["checked_columns", "findings", "ok", "skipped_columns", "tables"],
        "keys",
    )
    eq(payload["findings"][0]["code"], "no_relation", "finding code survives")
