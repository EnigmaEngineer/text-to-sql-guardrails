"""Score a table against a question by shared words. No model, no download.

This is the baseline the embedding has to beat. On a previous project of mine
bm25 beat a dense retriever on most of the metrics that mattered, so a lexical baseline
is not a straw man here.

The document for a table is its name plus its column names, split on underscores.
`fct_order_header` becomes fct, order, header. There are no column comments in this
schema, so that is genuinely all the text there is.

Scoring is idf weighted overlap rather than full bm25. With eighteen documents of
roughly ten words each, the length normalisation and term frequency saturation that bm25
adds have almost nothing to work on. Writing bm25 here would be writing a formula whose
distinguishing parts are inert.
"""

import math
import re

WORD = re.compile(r"[a-z0-9]+")

# words that appear in half the table names and carry no signal about which one
STOP = frozenset(
    "the a an of in on for by to and or is was were what which how many much"
    " show me list give all each per".split()
)


def stem(word):
    """Crude plural strip. Nothing more clever than this is justified here.

    Added after the first measurement, not before it. Without it the lexical scorer
    missed `fct_order_header` on seven questions, because every one of them says orders
    and the table says order. Losing a comparison on a plural is losing it on the
    baseline being sloppy rather than on the method. The 08-01 rule about never hand
    writing the side you expect to lose applies directly.
    """
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokens(text):
    return [
        stem(w)
        for w in WORD.findall(text.lower().replace("_", " "))
        if w not in STOP
    ]


def document(table):
    return " ".join([table.name] + [c.name for c in table.columns])


def idf(tables):
    n = len(tables)
    seen = {}
    for t in tables:
        for w in set(tokens(document(t))):
            seen[w] = seen.get(w, 0) + 1
    # smoothed so a word in every table scores near zero rather than negative
    return {w: math.log(1.0 + (n - df + 0.5) / (df + 0.5)) for w, df in seen.items()}


class Scorer:
    name = "lexical"

    def __init__(self, tables):
        self.tables = tables
        self.weights = idf(tables)
        self.docs = {t.name: set(tokens(document(t))) for t in tables}

    def scores(self, question):
        q = set(tokens(question))
        out = {}
        for t in self.tables:
            shared = q & self.docs[t.name]
            out[t.name] = sum(self.weights.get(w, 0.0) for w in shared)
        return out
