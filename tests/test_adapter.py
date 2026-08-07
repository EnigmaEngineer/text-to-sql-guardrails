from tests.harness import eq, raises, true
from warehouse import adapter


def check_duckdb_folds_down():
    d = adapter.get("duckdb")
    eq(d.fold("Order_Total"), "order_total", "duckdb fold")


def check_snowflake_folds_up():
    s = adapter.get("snowflake")
    eq(s.fold("Order_Total"), "ORDER_TOTAL", "snowflake fold")


def check_quoted_identifier_survives_both_dialects():
    # A quoted identifier keeps its case in both. Getting this backwards is how a
    # validator decides a real column does not exist.
    for name in ("duckdb", "snowflake"):
        eq(adapter.get(name).fold('"MixedCase"'), "MixedCase", "%s quoted" % name)


def check_explain_drops_trailing_semicolon():
    d = adapter.get("duckdb")
    eq(d.explain("SELECT 1;"), "EXPLAIN SELECT 1", "duckdb explain")
    eq(d.explain("SELECT 1  "), "EXPLAIN SELECT 1", "duckdb explain trailing space")


def check_snowflake_explain_asks_for_json():
    eq(adapter.get("snowflake").explain("SELECT 1"), "EXPLAIN USING JSON SELECT 1")


def check_snowflake_is_marked_unverified():
    # If this ever flips to True without a real Snowflake run behind it, every cost
    # number this project publishes becomes unfounded.
    true(adapter.get("duckdb").verified, "duckdb verified")
    eq(adapter.get("snowflake").verified, False, "snowflake verified")


def check_unknown_dialect_names_what_it_has():
    exc = raises(lambda: adapter.get("bigquery"), "unknown dialect", "get bigquery")
    true("duckdb" in str(exc), "error should list the dialects it does have")
