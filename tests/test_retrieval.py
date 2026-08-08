"""Checks on the scorers, the join graph and the completeness metric."""

from evals import power
from retrieval import graph, lexical, select
from tests.harness import eq, raises, true
from warehouse.catalog import Column, Table


def _table(name, *cols):
    return Table("retail", name, tuple(Column(name, c, "INTEGER", False) for c in cols))


FIXTURE = (
    _table("fct_order_header", "order_id", "customer_id", "order_date_key"),
    _table("dim_customer", "customer_id", "full_name"),
    _table("dim_date", "date_key", "year_number"),
    _table("fct_order_line", "line_id", "order_id", "product_id"),
    _table("dim_product", "product_id", "product_name"),
)
PKS = {
    "fct_order_header": "order_id",
    "dim_customer": "customer_id",
    "dim_date": "date_key",
    "dim_product": "product_id",
}


def check_stem_strips_a_plural():
    eq(lexical.stem("orders"), "order", "plural")
    eq(lexical.stem("order"), "order", "singular")


def check_stem_leaves_short_and_double_s_words():
    eq(lexical.stem("is"), "is", "short word")
    eq(lexical.stem("address"), "address", "double s")


def check_plural_question_matches_singular_table():
    """The whole reason `stem` exists. Without it this scores zero."""
    scorer = lexical.Scorer(FIXTURE)
    scores = scorer.scores("how many orders were placed")
    true(scores["fct_order_header"] > 0, "orders did not match fct_order_header")


def check_idf_discounts_a_word_in_every_table():
    shared = (_table("a", "shared_id"), _table("b", "shared_id"), _table("c", "shared_id"))
    weights = lexical.idf(shared)
    rare = lexical.idf(FIXTURE)
    true(weights["shared"] < rare["customer"], "a word in every table outweighed a rare one")


def check_ties_break_by_name_not_by_catalog_order():
    """A reversed catalog must give the same selection.

    Most questions leave most tables on zero, so the tie break decides a large share of
    what is retrieved. If it followed catalog order, the numbers in the report would be a
    property of how the tables happen to sort in information_schema.
    """
    forward = select.Retriever(lexical.Scorer(FIXTURE))
    backward = select.Retriever(lexical.Scorer(tuple(reversed(FIXTURE))))
    eq(
        forward.select("nothing matches this at all", 3),
        backward.select("nothing matches this at all", 3),
        "tie break",
    )


def check_edges_link_both_ways():
    links = graph.edges(FIXTURE, PKS)
    true("dim_customer" in links["fct_order_header"], "header to customer")
    true("fct_order_header" in links["dim_customer"], "customer to header")


def check_dim_date_has_no_inferred_edge():
    """Recorded as a check because it is the finding, not an accident.

    The primary key is `date_key` and the fact table carries `order_date_key`. The naming
    convention the rest of the schema follows breaks on the one dimension six questions
    need, and no scorer reading question text can find it either.
    """
    links = graph.edges(FIXTURE, PKS)
    eq(links["dim_date"], set(), "dim_date edges")


def check_expand_reaches_two_hops_only_when_asked():
    links = graph.edges(FIXTURE, PKS)
    one = graph.expand({"dim_product"}, links, hops=1)
    two = graph.expand({"dim_product"}, links, hops=2)
    true("fct_order_line" in one, "one hop")
    true("fct_order_header" not in one, "one hop reached too far")
    true("fct_order_header" in two, "two hops")


def check_complete_is_stricter_than_recall():
    """A fixture where three of four needed tables arrive.

    Recall says 0.75 and completeness says 0. A fixture where every question needs one
    table would report the same number twice and prove nothing.
    """

    class Fixed:
        name = "fixed"

        def scores(self, question):
            return {"a": 3.0, "b": 2.0, "c": 1.0, "d": 0.0}

    rows = [{"id": "q1", "question": "anything"}]
    rel = {"q1": frozenset({"a", "b", "c", "d"})}
    res = select.complete_at_k(select.Retriever(Fixed()), rows, rel, 3)
    eq(res["complete"], 0, "completeness")
    eq(round(res["table_recall"], 3), 0.75, "table recall")
    eq(res["misses"], [("q1", ["d"])], "the missing table")


def check_prompt_chars_matches_render_all():
    """Selecting everything must cost exactly what sending everything costs."""
    from warehouse import catalog

    everything = {t.name for t in FIXTURE}
    eq(
        select.prompt_chars(FIXTURE, everything),
        len(catalog.render_all(FIXTURE)),
        "whole schema char count",
    )


def check_prompt_chars_of_nothing_is_zero():
    eq(select.prompt_chars(FIXTURE, set()), 0, "empty selection")


def check_permutation_p_equals_the_floor_on_a_clean_sweep():
    """Seven differences all one way is the most lopsided result seven can give."""
    a = [0] * 7 + [1] * 15
    b = [1] * 22
    res = power.paired_permutation(a, b)
    eq(res["differing"], 7, "differing")
    eq(res["p"], res["p_floor"], "a clean sweep should return exactly the floor")
    true(res["p"] < 0.05, "seven one way should be decidable")


def check_permutation_refuses_mismatched_lengths():
    raises(
        lambda: power.paired_permutation([1, 0], [1, 0, 1]),
        "equal length",
        "mismatched vectors",
    )


def check_permutation_of_identical_vectors_is_not_a_result():
    res = power.paired_permutation([1, 0, 1], [1, 0, 1])
    eq(res["differing"], 0, "differing")
    eq(res["p"], 1.0, "p")
