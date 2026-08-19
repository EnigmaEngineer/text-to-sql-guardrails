"""Checks on prompt construction.

The interesting one is `check_every_stated_rule_is_enforced`. A prompt that lists rules
nobody checks reads like a control and is not one.
"""

from agent import guard, prompt as prompt_mod, role
from tests.harness import eq, true, raises
from warehouse import catalog

# One example of SQL that breaks each rule, in the order the rules are written. A rule
# with no example here fails the coupling check below rather than passing quietly.
# Every rule the prompt states must appear here exactly once, as either SQL that gets
# refused or an explicit note that it is not a SQL rule. On the gate this was a list of four
# against a RULES tuple of six, and the check that iterated it was called
# "every stated rule is enforced". It checked every rule someone had remembered to add.
# The two it skipped were the schema rule, which static validation is about, and the refusal token.
# It now iterates RULES, so a new rule with no enforcement fails the suite.
BREAKS_RULE = [
    ("Return exactly one", "SELECT 1; SELECT 2"),
    ("must be a SELECT", "DROP TABLE retail.fct_return"),
    ("COPY, EXPORT", "COPY (SELECT 1 AS a) TO '/tmp/x.csv'"),
    ("chain statements", "SELECT 1; SELECT 2"),
    ("tables and columns", "SELECT nope FROM retail.dim_customer"),
]

# A rule that is not about the SQL. It is enforced by the parser in agent.generate and
# the check below names where, rather than letting it go unaccounted for.
NOT_SQL_RULES = {"CANNOT_ANSWER": "agent.generate.parse"}


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
    """The first cut published 2,716 characters for the whole schema. Same renderer, same number.

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
    """Each rule in the prompt maps to SQL that is really refused, or is accounted for.

    Driven off `RULES` rather than off the fixture list, so adding a rule to the prompt
    without enforcing it fails here. That was the hole in the first version of this
    check and it is the same one door shape.
    """
    from warehouse import catalog

    tables = catalog.read(ctx.con)
    unmatched = []
    for rule in prompt_mod.RULES:
        fragments = [f for f, _sql in BREAKS_RULE if f in rule]
        excused = [k for k in NOT_SQL_RULES if k in rule]
        if len(fragments) + len(excused) != 1:
            unmatched.append(rule)
    eq(unmatched, [], "rules with no enforcement entry")

    for fragment, sql in BREAKS_RULE:
        matching = [r for r in prompt_mod.RULES if fragment in r]
        eq(len(matching), 1, "exactly one rule mentions %r" % fragment)
        v = guard.approve(ctx.con, tables, sql)
        true(not v.allowed, "SQL breaking %r is refused" % fragment)


def check_the_refusal_token_is_shared_not_retyped(ctx):
    from agent import generate

    true(prompt_mod.CANNOT_ANSWER in prompt_mod.render_rules(), "rules name the token")
    eq(generate.parse(prompt_mod.CANNOT_ANSWER)[0], "cannot_answer", "parser agrees")
