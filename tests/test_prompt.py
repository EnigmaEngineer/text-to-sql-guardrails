"""Checks on prompt construction.

The interesting one is `check_every_stated_rule_is_enforced`. A prompt that lists rules
nobody checks reads like a control and is not one.
"""

from agent import prompt as prompt_mod, role
from tests.harness import eq, true, raises
from warehouse import catalog

# One example of SQL that breaks each rule, in the order the rules are written. A rule
# with no example here fails the coupling check below rather than passing quietly.
BREAKS_RULE = [
    ("Return exactly one", "SELECT 1; SELECT 2"),
    ("must be a SELECT", "DROP TABLE retail.fct_return"),
    ("COPY, EXPORT", "COPY (SELECT 1 AS a) TO '/tmp/x.csv'"),
    ("chain statements", "SELECT 1; SELECT 2"),
]


def check_prompt_is_deterministic(ctx):
    tables = catalog.read(ctx.con)
    a = prompt_mod.build("How many orders?", tables).text
    b = prompt_mod.build("How many orders?", tables).text
    eq(a, b, "two builds of the same question")


def check_sizes_add_up(ctx):
    tables = catalog.read(ctx.con)
    p = prompt_mod.build("How many orders?", tables)
    s = p.sizes()
    eq(s["preamble"] + s["rules"] + s["schema"] + s["question"] + s["separators"],
       s["total"], "parts plus separators equal the whole")
    eq(s["total"], len(p.text), "total is the real length")


def check_schema_block_matches_the_published_size(ctx):
    """Day 1 published 2,716 characters for the whole schema. Same renderer, same number.

    Pinned so a schema change cannot move a figure the ADRs argue from without something
    failing first.
    """
    tables = catalog.read(ctx.con)
    eq(len(catalog.render_all(tables)), 2716, "whole schema characters")
    p = prompt_mod.build("q", tables)
    eq(len(p.schema), 2716 + len("Schema:\n"), "schema block is the schema plus its header")


def check_narrowing_shrinks_the_prompt(ctx):
    tables = catalog.read(ctx.con)
    whole = prompt_mod.build("q", tables)
    narrow = prompt_mod.build("q", tables, chosen={"dim_customer", "fct_order_header"})
    true(len(narrow.text) < len(whole.text), "narrowed prompt is smaller")
    true("dim_supplier" not in narrow.schema, "an unchosen table is absent")
    true("dim_customer" in narrow.schema, "a chosen table is present")


def check_empty_selection_is_refused(ctx):
    """A prompt with no schema in it would make the model invent table names."""
    tables = catalog.read(ctx.con)
    raises(lambda: prompt_mod.build("q", tables, chosen={"no_such_table"}),
           "selection is empty", "empty narrowing")


def check_empty_question_is_refused(ctx):
    tables = catalog.read(ctx.con)
    for q in ["", "   "]:
        raises(lambda: prompt_mod.build(q, tables), "no question", "blank question")


def check_question_survives_a_round_trip(ctx):
    """The scripted generator finds the question by splitting on the marker."""
    from agent import generate

    tables = catalog.read(ctx.con)
    asked = "Which store took the most orders in 2025?"
    text = prompt_mod.build(asked, tables).text
    eq(generate.question_of(text), asked, "question came back out")


def check_a_question_containing_the_marker_still_round_trips(ctx):
    """A question can contain the word the parser splits on.

    This failed on its first run. The splitter matched the bare marker and returned
    "mean in the ticket table?". It now anchors on the blank line between sections.
    Without the collision in the fixture the bug ships, which is the 08-02 lesson about
    fixtures that exercise one row.
    """
    from agent import generate

    tables = catalog.read(ctx.con)
    asked = "What does Question: mean in the ticket table?"
    text = prompt_mod.build(asked, tables).text
    eq(generate.question_of(text), asked, "marker inside the question")


def check_every_stated_rule_is_enforced(ctx):
    """Each rule in the prompt maps to SQL that the gate really refuses."""
    rules = prompt_mod.RULES
    for fragment, sql in BREAKS_RULE:
        matching = [r for r in rules if fragment in r]
        eq(len(matching), 1, "exactly one rule mentions %r" % fragment)
        d = role.inspect(ctx.con, sql)
        true(not d.allowed, "gate refuses the SQL breaking %r" % fragment)


def check_the_refusal_token_is_shared_not_retyped(ctx):
    from agent import generate

    true(prompt_mod.CANNOT_ANSWER in prompt_mod.render_rules(), "rules name the token")
    eq(generate.parse(prompt_mod.CANNOT_ANSWER)[0], "cannot_answer", "parser agrees")
