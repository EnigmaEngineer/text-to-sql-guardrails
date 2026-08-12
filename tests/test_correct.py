"""Checks on the correction policy, and on the list it is built from.

The first check is the important one. Everything else here tests behaviour that a reader
can see. `check_every_refusal_code_has_a_strategy` tests the thing nobody can see, which
is whether the policy still covers the codes the layers actually produce.
"""

import ast
import os

from agent import correct, prompt
from tests.harness import eq, raises, true

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT = os.path.join(ROOT, "agent")

# Where the refusal code sits in the positional arguments of each constructor. A
# `Finding` leads with its code. A `Decision` and a `Judgement` lead with the boolean.
CODE_POSITION = {"Finding": 0, "Decision": 1, "Judgement": 1, "Verdict": 2}

# `Verdict` and `Judgement` are also built for approvals, and an approval reason is not
# a refusal code. Filtered by the leading boolean where there is one.
ALLOWED_FIRST_ARG = {"Decision": 0, "Judgement": 0, "Verdict": 0}


def refusal_codes():
    """Every refusal code in agent/ that is built from a string literal.

    Reading the source rather than the strategy table is the whole point. A code added
    to `agent.validate` tomorrow appears here on its own, and the check below fails
    until somebody decides what the agent should say about it.

    Codes passed through from another module, such as `Verdict(False, "validate",
    first.code, ...)`, are not literals and are skipped. They are collected at the
    module that wrote them.
    """
    found = {}
    for name in sorted(os.listdir(AGENT)):
        if not name.endswith(".py") or name == "correct.py":
            continue
        path = os.path.join(AGENT, name)
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            ctor = node.func.id
            if ctor not in CODE_POSITION:
                continue
            args = node.args
            guard_at = ALLOWED_FIRST_ARG.get(ctor)
            if guard_at is not None:
                if len(args) <= guard_at:
                    continue
                first = args[guard_at]
                if not (isinstance(first, ast.Constant) and first.value is False):
                    continue
            at = CODE_POSITION[ctor]
            if len(args) <= at:
                continue
            arg = args[at]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.setdefault(arg.value, set()).add(name)
    return found


def check_the_scanner_finds_something():
    """A check that can pass on zero inputs will be pointed at zero inputs.

    Four things in this program have now reported clean on an empty list. The prose
    checker was one. The day 3 gate on a string of semicolons was another. So was
    `depcheck.py` with no arguments and the day 4 validator on a query with no base
    tables. A scanner is worth nothing without a floor under what it may find.
    """
    codes = refusal_codes()
    true(len(codes) >= 10, "found only %d refusal codes, the scanner is broken" % len(codes))
    for expected in ("not_a_read", "unknown_column", "over_ceiling", "table_function"):
        true(expected in codes, "%s not found by the scanner" % expected)


def check_every_refusal_code_has_a_strategy():
    """The check this module exists for.

    Derived from the source, never from a list beside it. On 08-10 a coupling check was
    named `check_every_stated_rule_is_enforced` and iterated a fixture list rather than
    the rule list, so it checked every rule somebody had remembered to add. This
    iterates the codes.
    """
    codes = refusal_codes()
    missing = sorted(c for c in codes if c not in correct.STRATEGY)
    eq(missing, [], "refusal codes with no correction strategy")


def check_no_strategy_is_written_for_a_code_that_cannot_happen():
    """The other direction. A strategy for a code nothing produces is dead prose."""
    codes = refusal_codes()
    extra = sorted(c for c in correct.STRATEGY if c not in codes)
    eq(extra, [], "strategies for refusal codes nothing produces")


def check_the_security_refusals_are_not_coached():
    """These three are intent rather than a slip. See the module docstring."""
    for code in ("not_a_read", "multiple_statements", "table_function"):
        eq(correct.STRATEGY[code].action, correct.STOP, "%s must not be coached" % code)
        eq(correct.STRATEGY[code].instruction, "", "%s must carry no instruction" % code)


def check_a_stop_strategy_says_why():
    for code, strategy in sorted(correct.STRATEGY.items()):
        if strategy.action == correct.STOP:
            true(strategy.why.strip(), "%s stops without a stated reason" % code)


def check_every_revise_strategy_actually_says_something():
    for code, strategy in sorted(correct.STRATEGY.items()):
        if strategy.action == correct.REVISE:
            true(len(strategy.instruction) > 20, "%s instruction is too thin" % code)


def check_the_novel_codes_are_the_ones_the_prompt_cannot_answer():
    """`novel` is a claim about the prompt and it gets checked rather than asserted.

    The prompt carries the rules and the whole schema. A refusal is novel when neither
    of those could have told the model about it in advance. A parser error, a row
    estimate and a plan operator are properties of the engine. Everything else here is
    a property of the query read against a schema the model was already holding.
    """
    eq(
        list(correct.NOVEL_CODES),
        ["no_estimate", "over_ceiling", "unparseable", "unscored_operator"],
        "codes carrying a fact the prompt did not",
    )
    for code in correct.NOVEL_CODES:
        eq(correct.STRATEGY[code].action, correct.REVISE, "%s is novel so it is worth a retry" % code)


def check_the_schema_refusals_are_not_marked_novel():
    """The schema goes into every prompt in full, so these were all checkable up front."""
    for code in ("unknown_table", "unknown_column", "no_relation", "cross_join"):
        eq(correct.STRATEGY[code].novel, False, "%s was answerable from the prompt" % code)


def check_each_instruction_talks_about_the_thing_that_was_wrong():
    """A mutant swapped the table and column instructions and nothing noticed.

    The earlier checks assert that the detail is carried through, which is true of any
    template. What they did not assert is that the sentence around it is about the right
    kind of mistake. A model told to check a column when it named a bad table is being
    pointed at the wrong place.
    """
    table_text = correct.STRATEGY["unknown_table"].instruction.lower()
    column_text = correct.STRATEGY["unknown_column"].instruction.lower()
    true("table" in table_text, "the table instruction mentions tables: %s" % table_text)
    true("column" not in table_text, "and not columns: %s" % table_text)
    true("column" in column_text, "the column instruction mentions columns: %s" % column_text)
    true("join" in correct.STRATEGY["unrelated_join"].instruction.lower(), "join")
    true("filter" in correct.STRATEGY["over_ceiling"].instruction.lower(), "narrowing")


def check_an_empty_correction_does_not_change_the_prompt(ctx):
    """Found by a mutant that appended the correction section unconditionally.

    An empty correction then added two characters to every prompt in the repo, which is
    invisible to a reader and drifts away from the prompt sizes day 3 published. The
    parser still worked, so nothing else caught it.

    Built off the real catalog rather than a hand made table. The first draft used a
    stub with a `name` and some columns, and `render_schema` wanted a `render` the stub
    did not have. That is the 08-05 lesson about a fixture shaped like what the test
    author imagined rather than like what the code reads.
    """
    from warehouse import catalog

    tables = catalog.read(ctx.con)
    plain = prompt.build("how many", tables)

    # Comparing an empty correction against another empty correction was the first
    # draft, and it passed against the mutant, because both sides carried the defect.
    # The assertion has to be about the text itself. Sections are joined by exactly one
    # blank line, so a dropped section shows up as a longer run of newlines.
    true("\n\n\n" not in plain.text, "no empty section in the default prompt")
    eq(len(plain.sections), 4, "four sections when there is nothing to correct")
    eq(plain.sizes()["correction"], 0, "counted as zero rather than missing")

    coached = prompt.build("how many", tables, correction="Fix the column.")
    eq(len(coached.sections), 5, "five when there is")
    true("\n\n\n" not in coached.text, "and still one blank line between them")
    eq(
        coached.sizes()["total"] - plain.sizes()["total"],
        len("Fix the column.") + 2,
        "a correction costs its own length plus one separator",
    )


def check_an_unknown_code_raises_rather_than_defaulting():
    """A default here would silently coach a refusal nobody decided to coach."""

    class FakeVerdict:
        reason = "brand_new_code"
        detail = ""

    class FakeAttempt:
        outcome = "refused"
        detail = "brand_new_code"
        verdict = FakeVerdict()

    raises(
        lambda: correct.correction_for(FakeAttempt()),
        "no correction strategy",
        "unknown refusal code",
    )


def check_an_unknown_outcome_raises():
    class FakeAttempt:
        outcome = "something_else"
        detail = ""
        verdict = None

    raises(lambda: correct.correction_for(FakeAttempt()), "unknown outcome", "bad outcome")


def check_an_answered_attempt_has_no_correction():
    class FakeAttempt:
        outcome = "answered"
        detail = ""
        verdict = None

    eq(correct.correction_for(FakeAttempt()), None, "nothing to correct")


def check_the_correction_carries_the_detail_not_the_code():
    """A model told `unknown_column` learns less than one told which column."""

    class FakeVerdict:
        reason = "unknown_column"
        detail = "dim_customer.favourite_colour is not in the catalog"

    class FakeAttempt:
        outcome = "refused"
        detail = "unknown_column"
        verdict = FakeVerdict()

    c = correct.correction_for(FakeAttempt())
    true("favourite_colour" in c.text, "the column is named: %s" % c.text)
    true(c.retryable, "worth another attempt")


def check_a_stopped_correction_renders_to_nothing():
    class FakeVerdict:
        reason = "table_function"
        detail = "read_csv() reads outside the catalog"

    class FakeAttempt:
        outcome = "refused"
        detail = "table_function"
        verdict = FakeVerdict()

    c = correct.correction_for(FakeAttempt())
    eq(c.action, correct.STOP, "not coached")
    eq(correct.render(c), "", "renders to nothing")
    true("read_csv" not in correct.render(c), "the payload is not echoed back")


def check_the_rendered_block_does_not_end_with_the_question_marker():
    """`generate.question_of` reads the last section as the question.

    A correction rendered with a trailing question marker would be read back as the
    question and the scripted fixtures would silently stop matching.
    """

    class FakeVerdict:
        reason = "unknown_table"
        detail = "fct_orders is not a table in the catalog"

    class FakeAttempt:
        outcome = "refused"
        detail = "unknown_table"
        verdict = FakeVerdict()

    block = correct.render(correct.correction_for(FakeAttempt()))
    true(prompt.CANNOT_ANSWER not in block, "no refusal token in the correction")
    true("\n\nQuestion: " not in block, "no question marker in the correction")
