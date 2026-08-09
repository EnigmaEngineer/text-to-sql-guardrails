"""Checks on parsing model output and on the generator fixtures."""

from agent import generate, prompt as prompt_mod
from tests.harness import eq, true, raises
from warehouse import catalog


def check_plain_sql_parses():
    kind, sql = generate.parse("SELECT 1")
    eq(kind, "sql", "kind")
    eq(sql, "SELECT 1", "text")


def check_fenced_sql_parses():
    for raw in [
        "```sql\nSELECT 1\n```",
        "```\nSELECT 1\n```",
        "  ```SQL\nSELECT 1\n```  ",
    ]:
        kind, sql = generate.parse(raw)
        eq(kind, "sql", "kind for %r" % raw[:12])
        eq(sql, "SELECT 1", "unfenced")


def check_a_fence_inside_the_query_is_not_stripped_twice():
    """The fence regex is anchored at both ends, so it takes the outer pair only."""
    kind, sql = generate.parse("```sql\nSELECT '```' AS a\n```")
    eq(kind, "sql", "kind")
    eq(sql, "SELECT '```' AS a", "inner backticks survive")


def check_refusal_token_parses():
    for raw in ["CANNOT_ANSWER", "  CANNOT_ANSWER  ", "CANNOT_ANSWER.", "```\nCANNOT_ANSWER\n```"]:
        eq(generate.parse(raw)[0], "cannot_answer", "refusal %r" % raw)


def check_a_query_mentioning_the_token_is_not_a_refusal():
    """Equality after stripping, not a substring test.

    A substring test would read this as a refusal and throw away a valid query. Built
    into the fixture rather than asserted in a comment.
    """
    kind, sql = generate.parse("SELECT 'CANNOT_ANSWER' AS a")
    eq(kind, "sql", "kind")
    true("CANNOT_ANSWER" in sql, "the literal is still there")


def check_empty_output_raises():
    raises(lambda: generate.parse(""), "empty string", "empty")
    raises(lambda: generate.parse("   \n  "), "empty string", "whitespace")
    raises(lambda: generate.parse(None), "returned None", "none")


def check_scripted_generator_replays(ctx):
    tables = catalog.read(ctx.con)
    g = generate.ScriptedGenerator({"How many orders?": "SELECT 1"})
    text = prompt_mod.build("How many orders?", tables).text
    eq(g.generate(text), "SELECT 1", "replayed")


def check_scripted_generator_is_loud_about_a_miss(ctx):
    tables = catalog.read(ctx.con)
    g = generate.ScriptedGenerator({"a": "SELECT 1"})
    text = prompt_mod.build("something else", tables).text
    raises(lambda: g.generate(text), "no scripted answer", "unscripted question")


def check_refusing_generator_refuses(ctx):
    eq(generate.RefusingGenerator().generate("anything"), prompt_mod.CANNOT_ANSWER, "floor")


def check_not_configured_says_why(ctx):
    raises(lambda: generate.NotConfigured().generate("x"),
           "never called a model", "unconfigured backend")


def check_question_of_needs_a_marker():
    raises(lambda: generate.question_of("no marker here"), "no question marker", "missing marker")
