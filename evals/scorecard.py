"""The whole eval set, one row per question, and the reason there is no accuracy figure.

The plan says "README with accuracy numbers on the eval set". There is no model
here and there never has been, so an accuracy number would be a statement about
`agent/generate.py`. What this repo can be scored on is the guard, and that is what this
module scores.

Two halves, and they are not the same kind of evidence.

The 22 answerable questions are run as their **gold SQL**, which is the frozen answer key.
A correct outcome is an approval. This half is in sample by construction. Every guardrail
here was run over the answer key before it shipped, because a rule I work to
is that a guardrail is judged first on what it refuses that it should not, and three checks
in `tests/` fail the build if any layer refuses a gold query. The first column rule
refused six of them and was rewritten. So this half does not measure the guard. It records
that a standing check is still green.

The eight refuse-tagged questions are run as **hand written plausible SQL** from
`evals.reach.PLAUSIBLE`, because the eval set records what should happen rather than a
query that should not run. That is the weak input and the only out of sample half. The
caveat travels with the number rather than sitting in a limitations section, per the
same rule.

**Pooling them is the mistake this module exists to make visible.** Score the two halves
together and a system with no guardrails at all reads 22 of 30, because it approves every
correct query and refuses nothing. That floor is not an argument, it is the `open` arm
below and it is measured. Everything seven days of guardrails contributed is the
difference between that arm and the real one.

Two readings of a refusal, and both are printed everywhere:

    any        the question was refused by something
    matching   it was refused by the layer its `refuse_reason` points at

`scripts/trace_report.py` printed the matching reading as `refused_by_something - 1` on
the correction loop. That was right at the time and it is arithmetic rather than a definition, which is
the whole problem. `OWNER` below is the definition and nothing subtracts one any more.
"""

from evals import reach

# Which guard stage owns each `refuse_reason` in the frozen eval set. None means no layer
# in this repo owns it, which is a fact about the plan rather than an oversight. No day of
# the plan carries a column policy, so `pii_export` has no owner and the README says so.
OWNER = {
    "write_operation": "gate",
    "not_in_schema": "validate",
    "unbounded_scan": "cost",
    "pii_export": None,
}

# The refuse half is scored against SQL nobody generated. Carried here so a reader of a
# scorecard meets it rather than a reader of the limitations section.
REFUSE_SQL_IS_HAND_WRITTEN = True


class Outcome:
    """One question, one row.

    `correct` is the whole judgement and it means different things on the two halves,
    which is the point. On an answerable question it means approved. On a refuse question
    it means refused, under whichever reading was asked for.
    """

    def __init__(self, qid, expect, refuse_reason, allowed, stage, code, error=""):
        self.qid = qid
        self.expect = expect
        self.refuse_reason = refuse_reason
        self.allowed = allowed
        self.stage = stage
        self.code = code
        self.error = error

    @property
    def raised(self):
        return self.stage == "raised"

    @property
    def owner(self):
        return OWNER.get(self.refuse_reason) if self.refuse_reason else None

    def correct(self, reading="any"):
        # An exception is not a refusal. It decided nothing and it took the caller with
        # it. Counting a crash as coverage is how an ablation flatters the layer it just
        # removed, so it is wrong on both halves.
        if self.raised:
            return False
        if self.expect == "answer":
            return self.allowed
        if self.allowed:
            return False
        if reading == "any":
            return True
        return self.stage == self.owner

    def __repr__(self):
        return "<%s %s %s>" % (self.qid, self.expect, self.stage)


class Scorecard:
    def __init__(self, arm, outcomes):
        self.arm = arm
        self.outcomes = list(outcomes)

    @property
    def answerable(self):
        return [o for o in self.outcomes if o.expect == "answer"]

    @property
    def refusable(self):
        return [o for o in self.outcomes if o.expect != "answer"]

    def approved_gold(self):
        return sum(1 for o in self.answerable if o.allowed)

    def refused(self, reading="any"):
        return sum(1 for o in self.refusable if o.correct(reading))

    def pooled(self, reading="any"):
        """The number nobody should publish, computed so it can be looked at."""
        return sum(1 for o in self.outcomes if o.correct(reading))

    def by_stage(self):
        out = {}
        for o in self.outcomes:
            if not o.allowed:
                out.setdefault(o.stage, []).append(o.qid)
        return out

    def raised(self):
        return [o for o in self.outcomes if o.raised]

    def mislabelled(self):
        """Refused, but not by the layer the label points at. The gap between readings."""
        return [
            o for o in self.refusable
            if not o.allowed and o.owner is not None and o.stage != o.owner
        ]

    def unowned(self):
        """Refuse questions no layer in this repo is responsible for."""
        return [o for o in self.refusable if o.owner is None]


def _sql_for(row):
    if row["expect"] == "answer":
        return row["gold_sql"]
    return reach.PLAUSIBLE[row["id"]]


def score(con, tables, rows, ceiling, approve, arm="real"):
    """Run every question in the set through `approve` and record what happened.

    `approve` is a parameter rather than an import so the arms below can pass a stub and
    so a test can score a known set of verdicts without a warehouse.
    """
    outcomes = []
    for row in rows:
        try:
            verdict = approve(con, tables, _sql_for(row), ceiling)
        except Exception as exc:                       # noqa: BLE001
            outcomes.append(
                Outcome(
                    row["id"], row["expect"], row.get("refuse_reason"),
                    False, "raised", type(exc).__name__,
                    str(exc).splitlines()[0],
                )
            )
            continue
        outcomes.append(
            Outcome(
                row["id"],
                row["expect"],
                row.get("refuse_reason"),
                verdict.allowed,
                verdict.stage,
                verdict.reason,
            )
        )
    return Scorecard(arm, outcomes)


class _Stub:
    """Minimum surface `score` reads off a verdict. Not `guard.Verdict`, on purpose.

    Building the arms out of the real Verdict would make them depend on a dataclass whose
    fields are about the real layers. These arms are not systems. They are the two ends of
    the range any scorecard on this set has to be read against.
    """

    def __init__(self, allowed, stage, reason):
        self.allowed = allowed
        self.stage = stage
        self.reason = reason


def open_guard(con, tables, sql, ceiling=None):
    """Approve everything. What the scorecard reads with no guardrails at all."""
    return _Stub(True, "approved", "no_guard")


def closed_guard(con, tables, sql, ceiling=None):
    """Refuse everything. The other end, and it is worth having.

    A metric where the do-nothing system scores well is a metric worth distrusting. This
    arm is what tells you whether the floor comes from approving or from refusing.
    """
    return _Stub(False, "gate", "refuse_everything")


def arms(con, tables, rows, ceiling, approve):
    """The real system between the two degenerate ones. Ordered worst to best is not
    assumed, because on a badly chosen metric it will not be."""
    return [
        score(con, tables, rows, ceiling, closed_guard, "refuse everything"),
        score(con, tables, rows, ceiling, open_guard, "approve everything"),
        score(con, tables, rows, ceiling, approve, "this repo"),
    ]


def ablate(con, tables, rows, ceiling, approve, layers_arg="layers"):
    """Score the guard with each layer removed, one at a time and then alone.

    Built by calling the shipped `approve` with a subset of its own layers rather than by
    writing a smaller guard here. A lesson I have learned is that a comparison
    you construct yourself is a comparison you can accidentally rig, and a hand written
    "gate only" would be a different program that happens to share a name.

    Every arm is scored with the same `score`, so a layer that raises instead of refusing
    is recorded as `raised` and counted wrong. That matters more than it sounds. Two of
    these arms crash, and an ablation that scored a crash as coverage would report the
    layer it just removed as unnecessary.
    """
    from agent import guard

    subsets = [
        ("all three", guard.LAYERS),
        ("no cost", (guard.GATE, guard.VALIDATE)),
        ("no validate", (guard.GATE, guard.COST)),
        ("no gate", (guard.VALIDATE, guard.COST)),
        ("gate only", (guard.GATE,)),
        ("validate only", (guard.VALIDATE,)),
        ("cost only", (guard.COST,)),
    ]
    cards = []
    for label, layers in subsets:
        def call(c, t, sql, ceil, _layers=layers):
            return approve(c, t, sql, ceil, **{layers_arg: _layers})

        cards.append(score(con, tables, rows, ceiling, call, label))
    return cards


def lower_bound(k, n, alpha=0.05, tol=1e-9):
    """Exact one sided lower confidence bound on a rate of k out of n.

    Solves P(X >= k | p) = alpha by bisection, which is the Clopper Pearson lower limit.
    Bisection keeps this on the standard library, and the same convention was used on the
    earlier project of mine so the two are comparable.

    5 of 8 is a handful of observations and printing 0.625 beside it invites a reader to
    treat it as a rate. The bound is what the count licenses.
    """
    if not 0 <= k <= n:
        raise ValueError("k must be between 0 and n, got %d of %d" % (k, n))
    if k == 0:
        return 0.0
    lo, hi = 0.0, 1.0
    while hi - lo > tol:
        mid = (lo + hi) / 2.0
        if _tail(k, n, mid) < alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _tail(k, n, p):
    """P(X >= k) for X binomial(n, p). Summed from the top, no factorials."""
    total = 0.0
    for i in range(k, n + 1):
        total += _choose(n, i) * (p ** i) * ((1.0 - p) ** (n - i))
    return total


def _choose(n, k):
    out = 1
    for i in range(k):
        out = out * (n - i) // (i + 1)
    return out
