import decimal

from evals import collision, freeze, gold, power
from tests.harness import eq, raises, true


def check_every_question_loads():
    rows = gold.load()
    eq(len(rows), 30, "question count")
    eq(len(gold.answerable(rows)), 22, "answerable count")


def check_ids_are_unique_and_padded():
    rows = gold.load()
    ids = [r["id"] for r in rows]
    eq(len(set(ids)), len(ids), "unique ids")
    true(all(i.startswith("q") and len(i) == 4 for i in ids), "id shape")


def check_refusals_carry_a_reason_and_no_sql():
    for r in gold.load():
        if r["expect"] == "refuse":
            true(bool(r.get("refuse_reason")), "%s reason" % r["id"])
            true("gold_sql" not in r, "%s should have no gold_sql" % r["id"])


def check_loader_rejects_an_answer_with_no_sql(tmp=None):
    import json
    import os
    import tempfile
    bad = [{"id": "q001", "expect": "answer", "question": "x"}]
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(bad[0]) + "\n")
    try:
        raises(lambda: gold.load(path), "no gold_sql", "loader on a missing gold_sql")
    finally:
        os.remove(path)


def check_loader_rejects_a_refusal_carrying_sql():
    import json
    import os
    import tempfile
    bad = {"id": "q001", "expect": "refuse", "refuse_reason": "dml",
           "question": "x", "gold_sql": "SELECT 1"}
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(bad) + "\n")
    try:
        raises(lambda: gold.load(path), "carries gold_sql", "loader on a refusal with sql")
    finally:
        os.remove(path)


def check_frozen_hash_matches_the_questions_file():
    rec = freeze.verify()
    eq(rec["questions"], 30, "frozen question count")
    eq(rec["answerable"], 22, "frozen answerable count")


def check_freeze_verify_names_the_freeze_date_when_it_fails():
    import json
    import os
    import tempfile
    fd, qpath = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps({"id": "q001", "expect": "answer", "question": "x",
                             "gold_sql": "SELECT 1"}) + "\n")
    fd, fpath = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump({"frozen_on": "2026-08-07", "sha256": "0" * 64,
                   "questions": 1, "answerable": 1, "note": ""}, fh)
    try:
        exc = raises(lambda: freeze.verify(qpath, fpath), "has changed since it was frozen")
        true("2026-08-07" in str(exc), "the error should name the freeze date")
        true("Do not refresh this hash" in str(exc), "the error should say what not to do")
    finally:
        os.remove(qpath)
        os.remove(fpath)


def check_canonical_makes_decimal_and_float_comparable():
    a = gold.canonical([(decimal.Decimal("4.00"),)])
    b = gold.canonical([(4.0,)])
    eq(a, b, "Decimal 4.00 and float 4.0 are the same answer")
    eq(gold.fingerprint(a), gold.fingerprint(b), "and should fingerprint the same")


def check_canonical_keeps_row_order():
    # q003 and q008 are top n questions. Sorting the rows away would let a system pass
    # by returning the right products in the wrong order.
    a = gold.canonical([(1,), (2,)])
    b = gold.canonical([(2,), (1,)])
    true(a != b, "row order must survive canonicalisation")
    true(gold.fingerprint(a) != gold.fingerprint(b), "and must change the fingerprint")


def check_canonical_separates_true_from_one():
    # DuckDB hands booleans back as bool and Python says True == 1. If canonical folded
    # them together, a count of 1 and a converted flag would fingerprint identically.
    true(gold.canonical([(True,)]) != gold.canonical([(1,)]), "True is not 1 here")


def check_collision_report_finds_a_real_collision():
    # The fixture has to contain a collision. A fixture where every group has one member
    # tests nothing about grouping, which is the 08-02 lesson.
    results = {
        "qA": ((("x",),), "aaaa"),
        "qB": ((("x",),), "aaaa"),
        "qC": ((("y",),), "bbbb"),
    }
    groups = collision.collisions(results)
    eq(len(groups), 1, "one colliding group")
    eq(groups[0], ("qA", "qB"), "the pair that collided")


def check_single_cell_detection():
    results = {
        "qA": (((7,),), "aaaa"),
        "qB": (((1, 2),), "bbbb"),
        "qC": (((1,), (2,)), "cccc"),
    }
    eq(collision.single_cell(results), ["qA"], "only a one by one answer is single cell")


def check_power_floor_matches_the_arithmetic():
    eq(power.p_floor(1), 1.0, "one differing question can only give p of 1")
    eq(power.p_floor(5), 2.0 / 32, "five differing")
    eq(round(power.p_floor(6), 6), round(2.0 / 64, 6), "six differing")
    eq(power.min_differing(0.05), 6, "questions needed for p below 0.05")
    eq(power.p_floor(0), 1.0, "zero differing")


def check_no_gold_answer_is_empty(ctx):
    # An empty gold answer is scored correct by any query returning nothing, including a
    # broken one. q006 shipped like this in the first draft of this file.
    results = gold.run_gold(ctx.con)
    eq(gold.unscoreable(results), [], "questions with an empty gold answer")


def check_gold_queries_all_run(ctx):
    results = gold.run_gold(ctx.con)
    eq(len(results), 22, "gold queries that executed")


def check_no_two_questions_share_an_answer(ctx):
    results = gold.run_gold(ctx.con)
    eq(collision.collisions(results), [], "questions sharing an answer")


def check_gold_results_are_stable_across_two_runs(ctx):
    a = gold.run_gold(ctx.con)
    b = gold.run_gold(ctx.con)
    for qid in a:
        eq(a[qid][1], b[qid][1], "%s fingerprint on a second run" % qid)


def check_equality_and_fingerprint_agree_on_every_gold_pair(ctx):
    # The collision detector groups by fingerprint. Anything comparing canonical rows
    # directly would use tuple equality. If the two ever disagree, one of them is lying.
    results = gold.run_gold(ctx.con)
    items = sorted(results.items())
    for i, (qa, (ca, fa)) in enumerate(items):
        for qb, (cb, fb) in items[i + 1:]:
            eq((ca == cb), (fa == fb), "%s vs %s, equality and fingerprint" % (qa, qb))


def check_unscoreable_actually_finds_an_empty_answer():
    # The real eval set has no empty answers, so the guard never fires against it. A
    # fixture that never triggers a rule does not test the rule. This is the 08-02
    # lesson applied to a guard rather than to a grouping.
    results = {
        "qA": ((), "empty"),
        "qB": (((1,),), "aaaa"),
    }
    eq(gold.unscoreable(results), ["qA"], "the empty answer should be named")


def check_loader_rejects_duplicate_ids():
    import json
    import os
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as fh:
        for _ in range(2):
            fh.write(json.dumps({"id": "q001", "expect": "answer", "question": "x",
                                 "gold_sql": "SELECT 1"}) + "\n")
    try:
        raises(lambda: gold.load(path), "duplicate question ids", "loader on duplicates")
    finally:
        os.remove(path)


def check_canonical_keeps_column_order_within_a_row():
    # Found by mutation. A mutant that sorted the cells inside each row survived every
    # other check in the suite. It would score a revenue and month pair as equal to the
    # same two values the other way round.
    a = gold.canonical([("2", 1)])
    b = gold.canonical([(1, "2")])
    true(a != b, "column order must survive canonicalisation")
    true(gold.fingerprint(a) != gold.fingerprint(b), "and must change the fingerprint")


def check_power_describe_separates_the_two_counts():
    # These are easy to conflate and the first version printed 30 next to the word
    # scorable while only 22 are scored against a gold answer.
    text = power.describe(30, 22)
    true("30 questions" in text, "should name the whole set")
    true("22 are scored against a gold answer" in text, "should name the gold subset")
