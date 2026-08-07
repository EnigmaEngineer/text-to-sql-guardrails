"""How often do two different questions have the same answer?

This is the hole in scoring by result set. If q012 and q017 return the same thing, a
system that answers q012 with q017's query is marked correct on both. The metric cannot
tell them apart and no amount of prompt work fixes that.

Measure it before trusting the score, not after.
"""

from collections import defaultdict


def collisions(results):
    """results is id -> (canon, fingerprint). Returns groups of ids sharing an answer."""
    by_print = defaultdict(list)
    for qid, (_canon, fp) in sorted(results.items()):
        by_print[fp].append(qid)
    return [tuple(ids) for ids in by_print.values() if len(ids) > 1]


def single_cell(results):
    """Questions whose answer is one row and one column.

    These are the collision risk. A single number is far more likely to be reached by a
    wrong query than a twelve row table is.
    """
    out = []
    for qid, (canon, _fp) in sorted(results.items()):
        if len(canon) == 1 and len(canon[0]) == 1:
            out.append(qid)
    return out


def report(results):
    groups = collisions(results)
    thin = single_cell(results)
    lines = [
        "answerable questions: %d" % len(results),
        "single cell answers:  %d  (%s)" % (len(thin), ", ".join(thin) or "none"),
        "colliding groups:     %d" % len(groups),
    ]
    for g in groups:
        lines.append("  same answer: %s" % ", ".join(g))
    return "\n".join(lines)
