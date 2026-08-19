from tests.harness import eq, raises, true
from warehouse import catalog


def check_reads_every_table(ctx):
    tables = catalog.read(ctx.con)
    eq(len(tables), 18, "table count")
    eq(sum(len(t.columns) for t in tables), 111, "column count")


def check_qualified_names_carry_the_schema(ctx):
    tables = {t.name: t for t in catalog.read(ctx.con)}
    eq(tables["fct_order_line"].qualified, "retail.fct_order_line")


def check_column_index_knows_real_and_fake_columns(ctx):
    idx = catalog.column_index(catalog.read(ctx.con))
    true(("fct_order_header", "order_total") in idx, "order_total should exist")
    true(("dim_customer", "loyalty_tier") in idx, "loyalty_tier should exist")
    # q030 asks for this one. It is the hallucination case and it must not be present.
    true(("dim_customer", "churn_probability") not in idx, "churn_probability is invented")
    true(("fct_order_header", "ordertotal") not in idx, "missing underscore is a miss")


def check_column_order_is_declaration_order(ctx):
    tables = {t.name: t for t in catalog.read(ctx.con)}
    names = [c.name for c in tables["fct_order_line"].columns]
    eq(names[0], "order_line_id", "first column")
    eq(names[-1], "net_amount", "last column")


def check_nullability_is_read_not_guessed(ctx):
    tables = {t.name: t for t in catalog.read(ctx.con)}
    cols = {c.name: c for c in tables["fct_order_header"].columns}
    eq(cols["order_total"].nullable, False, "order_total nullable")
    # store_id is null for online orders. A validator that assumes every FK is populated
    # will generate an inner join and silently drop half the orders.
    eq(cols["store_id"].nullable, True, "store_id nullable")


def check_empty_schema_says_so(ctx):
    raises(lambda: catalog.read(ctx.con, schema="does_not_exist"),
           "no columns found", "read of a missing schema")


def check_render_lists_columns_with_types(ctx):
    tables = {t.name: t for t in catalog.read(ctx.con)}
    text = tables["dim_channel"].render()
    true(text.startswith("retail.dim_channel("), "render prefix")
    true("is_online BOOLEAN" in text, "render should carry the type")


def check_column_index_folds_case():
    # DuckDB already hands back lower case names, so the folding in column_index does
    # nothing against the real warehouse and a mutant that removed it would survive.
    # Snowflake hands back upper case. Test it on hand built tables instead.
    tables = (
        catalog.Table("RETAIL", "FCT_ORDER_HEADER", (
            catalog.Column("FCT_ORDER_HEADER", "ORDER_TOTAL", "NUMBER", False),
        )),
    )
    idx = catalog.column_index(tables)
    true(("fct_order_header", "order_total") in idx, "upper case names should fold down")


def check_bridge_join_without_is_primary_fans_out(ctx):
    """The join trap this warehouse exists to contain, written down as a number.

    A product reaches a category two ways. Through dim_product.category_id, and through
    bridge_product_category where roughly half the products carry a second non primary
    row. Both paths agree when is_primary is respected. Dropping that filter inflates
    revenue and no error is raised, which is what makes it worth a static check.
    """
    def total(join):
        return float(ctx.con.execute(
            "SELECT round(sum(l.net_amount), 2) FROM retail.fct_order_line l "
            + join +
            " JOIN retail.fct_order_header h ON h.order_id = l.order_id"
            " WHERE h.order_status <> 'cancelled'"
        ).fetchone()[0])

    direct = total("JOIN retail.dim_product p ON p.product_id = l.product_id")
    primary = total("JOIN retail.bridge_product_category b"
                    " ON b.product_id = l.product_id AND b.is_primary")
    unfiltered = total("JOIN retail.bridge_product_category b"
                       " ON b.product_id = l.product_id")

    eq(primary, direct, "the two defensible paths must agree")
    true(unfiltered > direct * 1.3, "the unfiltered bridge join should inflate visibly")
