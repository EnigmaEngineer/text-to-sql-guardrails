"""Checks on the gold derived relevance labels.

The labels are not hand written, which removes one whole class of mistake and adds
another. Nobody can mislabel a question, because the gold SQL is the label. But the
extractor can be wrong, and if it is, every retrieval number in this repo is wrong with
it and nothing else would notice.
"""

from evals import gold
from retrieval import relevance
from tests.harness import eq, raises, true

CTE = "WITH recent AS (SELECT * FROM retail.fct_order_header) SELECT count(*) FROM recent"
SUBQUERY = (
    "SELECT count(*) FROM retail.dim_product p WHERE p.category_id IN "
    "(SELECT category_id FROM retail.dim_category WHERE department = 'Home')"
)
ALIASED = "SELECT x.order_id FROM retail.fct_order_header AS x LIMIT 1"


def check_cte_name_is_not_a_table(ctx):
    got = relevance.tables_in(ctx.con, CTE)
    eq(got, frozenset({"fct_order_header"}), "cte query")
    true("recent" not in got, "cte name leaked into the table set")


def check_subquery_tables_are_found(ctx):
    eq(
        relevance.tables_in(ctx.con, SUBQUERY),
        frozenset({"dim_product", "dim_category"}),
        "table inside a subquery",
    )


def check_alias_is_not_a_table(ctx):
    eq(relevance.tables_in(ctx.con, ALIASED), frozenset({"fct_order_header"}), "alias")


def check_string_literal_is_not_read_as_sql(ctx):
    """The reason for using the parser rather than a regex, stated as a check."""
    sql = "SELECT 'from retail.dim_employee' AS note FROM retail.dim_store"
    eq(relevance.tables_in(ctx.con, sql), frozenset({"dim_store"}), "literal")


def check_unparseable_sql_is_reported(ctx):
    raises(
        lambda: relevance.tables_in(ctx.con, "SELECT FROM WHERE"),
        "could not parse",
        "broken sql",
    )


def check_every_gold_query_yields_labels(ctx):
    rel = relevance.gold_relevance(ctx.con, gold.answerable())
    eq(len(rel), 22, "labelled questions")
    for qid, tables in rel.items():
        true(len(tables) >= 1, "%s has no tables" % qid)


def check_multi_table_questions_exist(ctx):
    """A label set where every question needs one table cannot test a completeness rule.

    The 08-02 fixture lesson. If every required set had size one, complete_at_k and plain
    recall would be the same number and the difference between them would never be
    exercised.
    """
    rel = relevance.gold_relevance(ctx.con, gold.answerable())
    multi = [q for q, t in rel.items() if len(t) > 1]
    true(len(multi) >= 10, "only %d questions need more than one table" % len(multi))


def check_coverage_names_the_unused_tables(ctx):
    rel = relevance.gold_relevance(ctx.con, gold.answerable())
    unused = relevance.coverage(rel, ["dim_date", "dim_employee", "not_a_real_table"])
    eq(unused, ["dim_employee", "not_a_real_table"], "unused tables")
