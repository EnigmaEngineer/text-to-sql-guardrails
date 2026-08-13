"""Cost estimation from a query plan, and the ceiling that refuses an expensive one.

This module is pure. It reads a plan document and judges it. It never runs anything,
because running an `EXPLAIN` on model SQL means handing model SQL to the connection and
that goes through `agent.guard` like everything else. See `guard.plan_of`.

Four things were measured on 2026-08-11 against duckdb 1.5.5 and they decided the whole
shape of this file.

**The plan's output cardinality is not usable.** Over the 22 answerable gold queries the
root node carries no `Estimated Cardinality` at all on 9 of them and reports exactly 0 on
another 11, against real answers of 4, 12 and 20 rows. Two carry a real number. So a
ceiling on "rows the user gets back" cannot be built from this plan, and the ceiling below
is on work done rather than on rows returned.

**Summing the scans is the wrong metric, and the losing side was built properly before it
lost.** `SELECT count(*) FROM fct_order_line l JOIN fct_web_session s ON l.quantity >
s.page_views` passes the day 4 validator cleanly, because its join condition names two
real tables. Summing its scan nodes gives 104,357, against a gold maximum of 70,523. That
is a factor of 1.48 and no ceiling lives in it. The maximum estimate over every node gives
223,844,302 against a gold maximum of 64,357, which is a factor of 3,478. One plan and one
walk of it. Only one of the two metrics separates anything.

**The estimate is not an upper bound.** Compared against real per operator counts from
DuckDB's own profiler, the estimate came in below the truth on 8 of the 22 gold queries,
worst at 0.23 of actual. So this ceiling refuses the obviously expensive query and can be
walked under by anything the optimizer underestimates. It is a filter on accidents, not a
defence against an adversary, and the README says so. That figure is printed by
`scripts/cost_report.py` rather than written into a sentence, because the first draft of
this paragraph said 5 and was wrong.

**The one operator guaranteed to explode is the one DuckDB will not estimate.** A
`CROSS_PRODUCT` node carries no `Estimated Cardinality`. So the comma cross join of two
tables at 64,357 and 40,000 rows has a maximum node estimate of 64,357, which is under any
ceiling the answer key permits, while the real product is 2.57 billion. A metric built on
"the largest number in the plan" reads an unestimated node as free. So a plan carrying an
operator nothing can be read off is refused on that basis rather than scored.
"""

from dataclasses import dataclass


class NothingToEstimate(Exception):
    """Not one node in the plan carried a number. That is a finding, not a clean bill.

    Four checks in this program have passed by looking at nothing. This module is not
    going to be the fifth.

    The first version of this rule was "no base table scan in the plan" and it was
    wrong. `SELECT count(*) FROM retail.dim_store` plans as a single `COLUMN_DATA_SCAN`
    with an estimate of 1, because DuckDB answers it from table metadata and never
    touches the table. So a cheap and obviously correct query was refused. No gold
    question is a bare count on one table, so the answer key check came back clean and
    said nothing while it happened. Refusing a query for reading no table is
    `agent.validate`'s job and it has a rule for it. This module's job is whether a cost
    can be read at all. Those are different questions that happened to agree on every
    query tried first.
    """


# Operators that carry no estimate and are known not to multiply. Anything else with no
# estimate is refused.
#
# The first draft of this was the other way round, a blocklist naming `CROSS_PRODUCT` and
# `NESTED_LOOP_JOIN` from memory. Measuring it killed both halves. A `NESTED_LOOP_JOIN`
# does carry an estimate, so that entry could never have fired. And a join on a function
# of both sides plans as `BLOCKWISE_NL_JOIN`, which carries none and was not in the list
# at all. A blocklist only refuses what its author already thought of.
#
# So this list is derived from the one set that must never be refused. These four are
# every operator that appears with no estimate across the 22 answerable gold queries,
# measured 2026-08-11. All four reduce or preserve row count. The cost of the inversion
# is that an unfamiliar operator gets refused even when it was harmless, which is the
# direction a guardrail should fail in, and it surfaces as a refusal someone can read
# rather than as silence.
#
# Two more were added on 2026-08-13 and they did NOT come off the answer key, which is
# worth stating because the paragraph above says the list is derived from it. `LIMIT` and
# `STREAMING_LIMIT` carry no estimate, and every gold query that limits also orders, which
# plans as `TOP_N`. So no gold query produces either name and the answer key check stayed
# green while `SELECT customer_id FROM retail.dim_customer LIMIT 5` was refused. A limit
# is the clearest non multiplying operator there is. Its output is bounded by its input
# and by the limit value at once, and the scan underneath it is still counted.
UNESTIMATED_AND_SAFE = frozenset(
    {
        "ORDER_BY", "UNGROUPED_AGGREGATE", "PERFECT_HASH_GROUP_BY", "TOP_N",
        "LIMIT", "STREAMING_LIMIT",
    }
)

# The four that really are derived from the answer key, kept separate so the claim in the
# comment above stays checkable and so a test can tell the two sources apart.
FROM_THE_ANSWER_KEY = frozenset(
    {"ORDER_BY", "UNGROUPED_AGGREGATE", "PERFECT_HASH_GROUP_BY", "TOP_N"}
)


@dataclass(frozen=True)
class Estimate:
    peak_rows: int              # largest estimate on any node, the metric the ceiling uses
    scanned_rows: int           # sum over base table scans, kept for the report
    scans: tuple                # (table, estimated rows), in plan order, can be empty
    unscored: tuple             # names of multiplying operators carrying no estimate
    nodes: int

    def as_dict(self):
        """For the trace. Day 6 wants the number and where it came from."""
        return {
            "peak_rows": self.peak_rows,
            "scanned_rows": self.scanned_rows,
            "scans": [{"table": t, "rows": n} for t, n in self.scans],
            "unscored": list(self.unscored),
            "nodes": self.nodes,
        }


@dataclass(frozen=True)
class Judgement:
    ok: bool
    code: str
    detail: str
    estimate: object = None
    ceiling: int = 0

    def as_dict(self):
        out = {
            "ok": self.ok,
            "code": self.code,
            "detail": self.detail,
            "ceiling": self.ceiling,
        }
        if self.estimate is not None:
            out["estimate"] = self.estimate.as_dict()
        return out


def _visit(nodes, seen):
    for node in nodes:
        info = node.get("extra_info") or {}
        raw = info.get("Estimated Cardinality")
        rows = None
        if raw is not None:
            # DuckDB writes it as a string in the JSON plan. An int() that quietly
            # becomes a float would compare fine and print wrong.
            rows = int(str(raw).replace(",", ""))
        seen.append((node.get("name", "?"), info.get("Table"), rows))
        _visit(node.get("children") or [], seen)
    return seen


def read_plan(plan):
    """Collect what one plan document says. Raises when there is nothing to read.

    `plan` is the parsed JSON from `EXPLAIN (FORMAT JSON)`, which is a list of root
    nodes. DuckDB gives one, and the loop does not assume that.
    """
    if not plan:
        raise NothingToEstimate("the plan document is empty")

    seen = _visit(plan, [])
    scored = [rows for _n, _t, rows in seen if rows is not None]
    if not scored:
        raise NothingToEstimate(
            "not one of %d node(s) carries an estimate: %s"
            % (len(seen), ", ".join(name for name, _t, _r in seen))
        )

    scans = tuple((table, rows or 0) for _name, table, rows in seen if table is not None)
    unscored = tuple(
        name for name, _table, rows in seen
        if rows is None and name not in UNESTIMATED_AND_SAFE
    )
    return Estimate(
        peak_rows=max(scored),
        scanned_rows=sum(rows for _table, rows in scans),
        scans=scans,
        unscored=unscored,
        nodes=len(seen),
    )


def judge(estimate, ceiling):
    """Compare an estimate against a ceiling and say which rule decided it.

    Codes are kept apart rather than collapsed into "too expensive", because day 6 has to
    tell a model what to change and "add a filter" and "name your join keys" are
    different instructions.
    """
    if ceiling <= 0:
        raise ValueError("ceiling must be positive, got %r" % ceiling)

    if estimate.unscored:
        return Judgement(
            False,
            "unscored_operator",
            "%s carries no row estimate, so the cost of this query is unknown rather "
            "than low" % ", ".join(sorted(set(estimate.unscored))),
            estimate,
            ceiling,
        )
    if estimate.peak_rows > ceiling:
        return Judgement(
            False,
            "over_ceiling",
            "largest estimated step is %d rows against a ceiling of %d"
            % (estimate.peak_rows, ceiling),
            estimate,
            ceiling,
        )
    return Judgement(True, "within_ceiling", "", estimate, ceiling)


def warehouse_ceiling(con, schema="retail"):
    """A ceiling read off the warehouse rather than tuned against the eval set.

    The reason has to come from somewhere other than the questions this is about to be
    judged on. On 08-06 a threshold was set at 1.0 and left untuned for exactly that
    reason. Here the argument is that no single question the agent is asked should make
    the engine handle more rows than the warehouse contains. A query that does is either
    joining a table to itself or multiplying two facts together, and neither is a
    question anyone typed. It is not a tight bound and is not meant to be. On this
    warehouse it lands at 3.2x the most expensive step in the answer key.

    `duckdb_tables()` rather than a `count(*)` per table, for two reasons. It is one
    literal statement instead of eighteen built by string formatting, which the day 4
    structural check refused when this was first written, and it was right to. And
    `estimated_size` is the same number the planner puts on a scan node, so the ceiling
    and the thing measured against it come from one source. A ceiling in exact rows
    compared against a planner estimate would be two units wearing one name.
    """
    rows = con.execute(
        "SELECT sum(estimated_size) FROM duckdb_tables() WHERE schema_name = ?",
        [schema],
    ).fetchone()
    total = int(rows[0] or 0)
    if total <= 0:
        raise NothingToEstimate("schema %r is empty, so a ceiling from it means nothing" % schema)
    return total
