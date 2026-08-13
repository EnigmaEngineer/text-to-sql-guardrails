"""Checks on the day 7 scorecard, and on the `layers` argument it needed.

The three that matter most run no SQL.

`check_a_raise_is_not_coverage` is the one the ablation rests on. Two of the seven arms
crash, and if a crash scored as a refusal then the ablation would report the layer it had
just removed as unnecessary. That is the shape of every measurement error this project
has caught, which is a check being right about the wrong thing.

`check_the_matching_reading_is_not_refused_minus_one` exists because that is exactly what
`scripts/trace_report.py` printed on day 6. It was correct on the day and it was
arithmetic rather than a definition, and `ot-037` is the thread about figures with no
producer behind them. The fixture here has a gap of two, so anything subtracting one
fails.

`check_the_owner_table_is_driven_off_the_eval_set` is the 08-10 lesson from this program.
A coupling check that iterates a list beside the thing it is checking will pass while
missing whatever nobody remembered to add.
"""

import ast
import json
import os

from agent import guard
from evals import scorecard
from tests.harness import eq, raises, true
from warehouse import catalog

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT_DIR = os.path.join(ROOT, "agent")
QUESTIONS = os.path.join(ROOT, "evals", "questions.jsonl")


def _rows():
    with open(QUESTIONS, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _tables(ctx):
    return catalog.read(ctx.con)


def _outcome(qid, expect, reason, allowed, stage, code="c"):
    return scorecard.Outcome(qid, expect, reason, allowed, stage, code)


# --- the readings ------------------------------------------------------------------


def check_a_raise_is_not_coverage():
    """A crash decided nothing. It is wrong on an answer and wrong on a refusal."""
    crashed_answer = _outcome("q001", "answer", None, False, "raised", "BinderException")
    crashed_refuse = _outcome("q023", "refuse", "write_operation", False, "raised", "Oops")
    true(not crashed_answer.correct("any"), "a crash on an answerable question")
    true(not crashed_refuse.correct("any"), "a crash on a refusal question, any reading")
    true(not crashed_refuse.correct("matching"), "same under the matching reading")
    true(crashed_refuse.raised, "and it is reported as raised rather than refused")


def check_the_matching_reading_is_not_refused_minus_one():
    """A gap of two. Anything subtracting one from the any reading fails this."""
    card = scorecard.Scorecard("fixture", [
        _outcome("a", "refuse", "unbounded_scan", False, "validate"),   # owner is cost
        _outcome("b", "refuse", "write_operation", False, "validate"),  # owner is gate
        _outcome("c", "refuse", "not_in_schema", False, "validate"),    # owner is validate
    ])
    eq(card.refused("any"), 3, "refused by something")
    eq(card.refused("matching"), 1, "refused by the owning layer")
    eq(len(card.mislabelled()), 2, "the gap between the two readings")


def check_an_unowned_refusal_is_never_matching():
    """`pii_export` has no owning layer. Refusing it by accident is not coverage of it."""
    o = _outcome("q026", "refuse", "pii_export", False, "validate")
    true(o.correct("any"), "something refused it")
    true(not o.correct("matching"), "but no layer owns pii_export")
    true(o.owner is None, "owner")


def check_an_approved_refusal_question_is_wrong_both_ways():
    o = _outcome("q028", "refuse", "unbounded_scan", True, "approved")
    true(not o.correct("any"), "any")
    true(not o.correct("matching"), "matching")


# --- the eval set and the owner table ----------------------------------------------


def check_the_owner_table_is_driven_off_the_eval_set():
    """Every `refuse_reason` in the frozen set has an entry, including the None ones.

    Iterating OWNER instead would check every reason somebody remembered to add.
    """
    reasons = {r["refuse_reason"] for r in _rows() if r["expect"] != "answer"}
    missing = sorted(r for r in reasons if r not in scorecard.OWNER)
    eq(missing, [], "refuse_reasons with no OWNER entry")
    stray = sorted(k for k in scorecard.OWNER if k not in reasons)
    eq(stray, [], "OWNER entries no question uses")


def check_every_owner_is_a_real_guard_layer_or_none():
    for reason, owner in scorecard.OWNER.items():
        true(owner is None or owner in guard.LAYERS,
             "owner of %s is a real layer or None" % reason)


def check_the_refuse_half_has_hand_written_sql_and_says_so():
    """The weak input is flagged at the point of use, not in a limitations section."""
    true(scorecard.REFUSE_SQL_IS_HAND_WRITTEN, "the flag is set")
    from evals import reach
    ids = {r["id"] for r in _rows() if r["expect"] != "answer"}
    eq(sorted(reach.PLAUSIBLE), sorted(ids), "every refuse question has plausible sql")


# --- the arms ----------------------------------------------------------------------


def check_the_open_arm_is_the_floor_and_it_is_measured(ctx):
    """Approve everything and the pooled score is the number of answerable questions.

    This is the whole point of the day. If it ever stops being true the floor argument in
    the README is wrong and the number beside it is worse than useless.
    """
    rows = _rows()
    card = scorecard.score(ctx.con, _tables(ctx), rows, None, scorecard.open_guard, "open")
    answerable = sum(1 for r in rows if r["expect"] == "answer")
    eq(card.pooled("any"), answerable, "pooled score of a system with no guardrails")
    eq(card.refused("any"), 0, "it refuses nothing")


def check_the_closed_arm_scores_worse_than_the_open_one(ctx):
    """A metric where refusing everything wins is a metric to throw away."""
    rows = _rows()
    tables = _tables(ctx)
    closed = scorecard.score(ctx.con, tables, rows, None, scorecard.closed_guard, "closed")
    open_ = scorecard.score(ctx.con, tables, rows, None, scorecard.open_guard, "open")
    true(closed.pooled("any") < open_.pooled("any"), "closed scores below open")


def check_the_real_arm_beats_the_open_one(ctx):
    from agent import cost
    rows = _rows()
    tables = _tables(ctx)
    ceiling = cost.warehouse_ceiling(ctx.con)
    real = scorecard.score(ctx.con, tables, rows, ceiling, guard.approve, "real")
    open_ = scorecard.score(ctx.con, tables, rows, ceiling, scorecard.open_guard, "open")
    true(real.pooled("any") > open_.pooled("any"), "the guard is worth something")
    eq(real.approved_gold(), sum(1 for r in rows if r["expect"] == "answer"),
       "no gold query is refused")


# --- the layers argument -----------------------------------------------------------


def check_approve_with_no_layers_raises_rather_than_approving(ctx):
    """The failure mode this argument creates, closed on purpose.

    Assert the message and not the type, per 08-02. A ValueError here could come from
    anywhere.
    """
    raises(
        lambda: guard.approve(ctx.con, _tables(ctx), "SELECT 1", None, ()),
        "not an open door",
        "approve with no layers",
    )


def check_approve_rejects_a_layer_name_it_does_not_have(ctx):
    raises(
        lambda: guard.approve(ctx.con, _tables(ctx), "SELECT 1", None, ("gate", "pii")),
        "unknown layer",
        "approve with a made up layer",
    )


def check_nothing_in_agent_passes_the_layers_argument():
    """The escape hatch is for the ablation and for nothing else.

    A keyword nobody in `agent/` uses cannot become a way to turn the guard down in a
    six week old call site. This reads the code rather than the behaviour, which is the
    only kind of check that catches that.
    """
    offenders = []
    for name in sorted(os.listdir(AGENT_DIR)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(AGENT_DIR, name)
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg == "layers":
                    offenders.append("%s:%d" % (name, node.lineno))
    eq(offenders, [], "calls in agent/ passing layers=")


def check_taking_the_cost_layer_away_changes_nothing_on_this_set(ctx):
    """Not a happy check. It is the day 7 finding and it is pinned so it cannot drift.

    If a later change makes the cost layer refuse something in the frozen set, this fails
    and the README paragraph built on it has to be rewritten. That is the intent.
    """
    from agent import cost
    rows = _rows()
    tables = _tables(ctx)
    ceiling = cost.warehouse_ceiling(ctx.con)
    full = scorecard.score(ctx.con, tables, rows, ceiling, guard.approve, "all")
    without = scorecard.score(
        ctx.con, tables, rows, ceiling,
        lambda c, t, s, ce: guard.approve(c, t, s, ce, (guard.GATE, guard.VALIDATE)),
        "no cost",
    )
    eq(without.pooled("any"), full.pooled("any"), "pooled score without the cost layer")
    eq(without.refused("any"), full.refused("any"), "refusals without the cost layer")


def check_running_cost_first_crashes_rather_than_refusing(ctx):
    """Day 5 put cost last because EXPLAIN binds. Here is the cruder second reason.

    On a write and on an unknown column the plan request raises out of the guard. A layer
    that explodes instead of refusing cannot be the first one.
    """
    from agent import cost
    rows = _rows()
    tables = _tables(ctx)
    ceiling = cost.warehouse_ceiling(ctx.con)
    card = scorecard.score(
        ctx.con, tables, rows, ceiling,
        lambda c, t, s, ce: guard.approve(c, t, s, ce, (guard.COST,)),
        "cost only",
    )
    true(len(card.raised()) > 0, "the cost layer alone raises on something")
    codes = {o.code for o in card.raised()}
    true("InvalidInputException" in codes,
         "EXPLAIN on a write raises, it does not refuse")


# --- the bound ---------------------------------------------------------------------


def check_the_lower_bound_reproduces_two_figures_from_an_earlier_project():
    """Anchors, not self consistency. Both were computed independently on 2026-08-06."""
    eq(round(scorecard.lower_bound(10, 10), 3), 0.741, "10 of 10")
    eq(round(scorecard.lower_bound(3, 10), 3), 0.087, "3 of 10")


def check_the_lower_bound_satisfies_its_own_defining_equation():
    """P(X >= k | p) is alpha at the bound. Checked on the case the README quotes."""
    for k, n in [(5, 8), (3, 10), (10, 10), (1, 4), (7, 7)]:
        p = scorecard.lower_bound(k, n)
        tail = scorecard._tail(k, n, p)
        true(abs(tail - 0.05) < 1e-6,
             "tail at the bound for %d of %d is 0.05, got %.8f" % (k, n, tail))


def check_the_lower_bound_on_the_degenerate_counts():
    """Zero successes licenses nothing. All successes still does not license one."""
    eq(scorecard.lower_bound(0, 8), 0.0, "0 of 8")
    true(scorecard.lower_bound(8, 8) < 1.0, "8 of 8 is not certainty")
    true(scorecard.lower_bound(5, 8) < 5.0 / 8.0, "the bound sits below the point estimate")
    raises(lambda: scorecard.lower_bound(9, 8), "between 0 and n", "k larger than n")


def check_the_bound_falls_as_the_count_shrinks():
    """More observations at the same rate buy a higher bound. A monotonicity a wrong
    implementation is unlikely to have by accident."""
    small = scorecard.lower_bound(5, 8)
    large = scorecard.lower_bound(50, 80)
    true(large > small, "80 observations at the same rate license more than 8")


def check_excluding_the_cost_layer_really_excludes_it(ctx):
    """The companion to the check above, and a mutant is why it exists.

    `check_taking_the_cost_layer_away_changes_nothing_on_this_set` passes whether or not
    the layer was skipped, because the layer changes nothing on that set either way. A
    mutant making `layers` ignore the cost entry survived it. This one uses a query the
    cost layer does refuse, so the two arms have to differ.
    """
    from agent import cost
    runaway = (
        "SELECT l.order_line_id, s.session_id FROM retail.fct_order_line l "
        "JOIN retail.fct_web_session s ON l.quantity > s.page_views"
    )
    tables = _tables(ctx)
    ceiling = cost.warehouse_ceiling(ctx.con)
    with_cost = guard.approve(ctx.con, tables, runaway, ceiling)
    without = guard.approve(ctx.con, tables, runaway, ceiling,
                            (guard.GATE, guard.VALIDATE))
    true(not with_cost.allowed, "the cost layer refuses it")
    eq(with_cost.stage, "cost", "stage")
    true(without.allowed, "and without the cost layer it is approved")
