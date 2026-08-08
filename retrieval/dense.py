"""Embedding scorer. bge-small-en-v1.5 over the same table text the lexical scorer reads.

This is the "schema embedding" half of the day. It is a separate module from the lexical
scorer and both expose `scores(question)`, so the report runs them through identical
code and any difference between them is the scorer rather than the harness.

No vector index. Eighteen vectors is a dot product against a matrix with eighteen rows.
An index here would be a dependency doing nothing, and the project plan naming FAISS is
not a reason to import it.

Two things carried in from the earlier retrieval project. Torch charges its warmup to the
first forward pass rather than to construction, so anything timing this has to push a
throwaway query through the model first. And the model download is about 130 MB, which
matters on a fresh machine and not afterwards.
"""

import os

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
MODEL = "BAAI/bge-small-en-v1.5"


class Scorer:
    name = "dense"

    def __init__(self, tables, model_name=MODEL, threads=2):
        import torch
        from sentence_transformers import SentenceTransformer

        from retrieval.lexical import document

        torch.set_num_threads(threads)
        self.model = SentenceTransformer(model_name)
        self.tables = tables
        self.names = [t.name for t in tables]
        # a table is described by the same words the lexical scorer gets, so the
        # comparison is between the two ways of matching and not between two inputs
        self.matrix = self.model.encode(
            [document(t).replace("_", " ") for t in tables],
            normalize_embeddings=True,
        )
        self.warm()

    def warm(self):
        """First forward pass is slow. Spend it before anything is measured."""
        self.model.encode([QUERY_PREFIX + "warmup"], normalize_embeddings=True)

    def scores(self, question):
        vec = self.model.encode(
            [QUERY_PREFIX + question], normalize_embeddings=True
        )[0]
        sims = self.matrix @ vec
        return {name: float(sims[i]) for i, name in enumerate(self.names)}


def available():
    try:
        import sentence_transformers  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        return False
    return True
