"""Pick the tables that go into the prompt, and say how much text that costs.

The measurement that matters is not how well the ranking orders tables. It is whether
every table the answer needs made it in. A question needing four tables where three
arrive is not three quarters right. The generated SQL cannot be correct at all. So the
headline number here is `complete_at_k`, the share of questions where the whole required
set is present, and it is a ceiling on end to end accuracy rather than a score.

Recall over tables is reported next to it because the two disagree in a useful way. A
high per table recall with a low complete rate means the misses are spread across many
questions, which is worse than the same recall concentrated in a few.
"""

from retrieval import graph


class Retriever:
    def __init__(self, scorer, links=None, hops=0):
        self.scorer = scorer
        self.links = links or {}
        self.hops = hops

    @property
    def name(self):
        return self.scorer.name + ("+join" if self.hops else "")

    def select(self, question, k):
        scores = self.scorer.scores(question)
        # ties broken by name so a rerun gives the same set, and so a table that scores
        # zero cannot win a place by being early in the catalog
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        picked = [name for name, _ in ranked[:k]]
        if self.hops:
            return graph.expand(picked, self.links, self.hops)
        return set(picked)


def complete_at_k(retriever, questions, relevance, k):
    """Share of questions whose entire required table set is retrieved."""
    complete = 0
    found = needed = 0
    misses = []
    for row in questions:
        want = relevance.get(row["id"])
        if want is None:
            continue
        got = retriever.select(row["question"], k)
        hit = want & got
        found += len(hit)
        needed += len(want)
        if hit == want:
            complete += 1
        else:
            misses.append((row["id"], sorted(want - got)))
    n = sum(1 for r in questions if r["id"] in relevance)
    return {
        "k": k,
        "complete": complete,
        "n": n,
        "complete_rate": complete / n if n else 0.0,
        "table_recall": found / needed if needed else 0.0,
        "misses": misses,
    }


def prompt_chars(tables, chosen):
    """Characters of schema text for a chosen set. What retrieval is meant to save.

    Rendered the same way `catalog.render_all` renders the whole schema, one table per
    line. Counting a trailing newline on the last line would put this a character above
    the figure first published for the full schema, which is the kind of one character
    disagreement that wastes an afternoon later.
    """
    picked = [t for t in tables if t.name in chosen]
    if not picked:
        return 0
    return sum(len(t.render()) for t in picked) + len(picked) - 1


def missed_tables(result):
    """Flat count of how often each table is the one that was missed."""
    counts = {}
    for _qid, missing in result["misses"]:
        for name in missing:
            counts[name] = counts.get(name, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
