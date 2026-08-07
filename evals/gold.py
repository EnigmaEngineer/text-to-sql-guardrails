"""Load the frozen eval set and run the gold SQL.

The eval scores an answer, not a query string. Two people write the same question three
different ways in SQL and all three are right, so string comparison would fail correct
work. What the harness compares is the result set.

That trade has a cost and `evals/collision.py` measures it. Two different questions can
land on the same answer, and when they do, a system that generates the wrong query for
one of them still scores correct.
"""

import decimal
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
QUESTIONS = os.path.join(HERE, "questions.jsonl")


def load(path=QUESTIONS):
    with open(path) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate question ids in %s" % path)
    for r in rows:
        if r["expect"] == "answer" and not r.get("gold_sql"):
            raise ValueError("%s expects an answer and has no gold_sql" % r["id"])
        if r["expect"] == "refuse" and r.get("gold_sql"):
            raise ValueError("%s expects a refusal and carries gold_sql" % r["id"])
        if r["expect"] == "refuse" and not r.get("refuse_reason"):
            raise ValueError("%s expects a refusal and gives no reason" % r["id"])
    return rows


def answerable(rows=None):
    return [r for r in (rows or load()) if r["expect"] == "answer"]


def canonical(rows):
    """Turn a result set into something comparable and hashable.

    Numbers are the awkward part. DuckDB hands back Decimal for a DECIMAL column and
    float for an average, and Decimal('4.00') != 4.0 in Python while both are the same
    answer. Everything numeric is normalised to a float rounded to 6 places.

    Row order is NOT sorted away. A question that asks for a top ten is asking about
    order, so throwing it away would let a system pass by returning the right ten rows
    backwards.

    Two canonical results compare equal exactly when their fingerprints match. That
    invariant is checked in tests and it is not free. Booleans have to be tagged to hold
    it, because True == 1 in Python and json writes them differently.
    """
    out = []
    for row in rows:
        cells = []
        for v in row:
            if isinstance(v, decimal.Decimal):
                cells.append(round(float(v), 6))
            elif isinstance(v, bool):
                # Tagged, because Python says True == 1 and a bare bool would make a
                # boolean answer compare equal to a count of one. The fingerprint
                # separated them already, so equality and hashing disagreed until this.
                cells.append(("bool", v))
            elif isinstance(v, float):
                cells.append(round(v, 6))
            elif isinstance(v, int):
                cells.append(v)
            elif v is None:
                cells.append(None)
            else:
                cells.append(str(v))
        out.append(tuple(cells))
    return tuple(out)


def fingerprint(canon):
    return hashlib.sha256(
        json.dumps(canon, default=str, sort_keys=False).encode()
    ).hexdigest()[:16]


def run_gold(con, rows=None):
    """Execute every gold query. Returns id -> (canonical rows, fingerprint)."""
    results = {}
    for r in answerable(rows):
        raw = con.execute(r["gold_sql"]).fetchall()
        canon = canonical(raw)
        results[r["id"]] = (canon, fingerprint(canon))
    return results


def unscoreable(results):
    """Questions whose gold answer cannot distinguish a right query from a broken one.

    An empty result set is the case that matters. Any query that returns nothing scores
    correct against it, including one that read the wrong table, and including one whose
    filter happens to exclude everything. q006 shipped like this in the first draft
    because its threshold was above the largest value in the column.
    """
    return sorted(qid for qid, (canon, _fp) in results.items() if len(canon) == 0)
