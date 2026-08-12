"""Build the prompt. Deterministic, measurable, and assembled from named parts.

Two decisions carried in from earlier days.

`adr-0005` measured retrieval on this warehouse and found the prize is under 600
characters on a 2,716 character schema. So the default here sends the whole schema and
`tables` is an optional narrowing that day 7 reports as a separate column. The retrieval
layer is still built and still tested. It is just not on the path by default.

`adr-0004` says there is no token budget, because the tokeniser belongs to a model that
has not been chosen. Everything here is counted in characters. A character count is true
regardless of which model reads it. A token count invented before the model is chosen is
a number that will quietly be wrong.

The sections are separate so `sizes()` can say what each one costs. When a prompt gets
too long the useful question is which part grew, and a single string cannot answer it.
"""

from dataclasses import dataclass

from warehouse import catalog

# What the model is told it may produce. Every line here is enforced by `agent.role`,
# and `tests/test_prompt.py` checks that a query breaking each rule is really refused.
# A rule stated in the prompt and not enforced is worse than no rule, because it reads
# like a control.
RULES = (
    "Return exactly one SQL statement and nothing else.",
    "It must be a SELECT. No INSERT, UPDATE, DELETE, CREATE, DROP or ALTER.",
    "Do not use COPY, EXPORT or any form that writes to a file.",
    "Do not chain statements with a semicolon.",
    "Use only the tables and columns listed in the schema below.",
    "If the question cannot be answered from this schema, reply exactly: CANNOT_ANSWER",
)

# The refusal token is checked for equality, so it is defined once and imported rather
# than typed again in the parser. Day 4 reads this.
CANNOT_ANSWER = "CANNOT_ANSWER"

PREAMBLE = (
    "You are a SQL analyst with read-only access to a retail warehouse.\n"
    "Answer the question with one query against the schema given below."
)


@dataclass(frozen=True)
class Prompt:
    preamble: str
    rules: str
    schema: str
    question: str
    correction: str = ""

    @property
    def sections(self):
        """In order. An empty correction is dropped rather than sent as a blank block.

        The correction sits before the question and not after it. `generate.question_of`
        takes the question to be the last section, so a correction appended at the end
        would be read back as the question and every retry would go unscripted.
        """
        parts = [self.preamble, self.rules, self.schema]
        if self.correction:
            parts.append(self.correction)
        parts.append(self.question)
        return parts

    @property
    def text(self):
        return "\n\n".join(self.sections)

    def sizes(self):
        """Characters per section, plus the joins between them.

        The parts do not add up to the whole on their own, so the separators are counted
        rather than left as a three character discrepancy for someone to find later.
        """
        parts = {
            "preamble": len(self.preamble),
            "rules": len(self.rules),
            "schema": len(self.schema),
            "correction": len(self.correction),
            "question": len(self.question),
        }
        parts["separators"] = len(self.text) - sum(parts.values())
        parts["total"] = len(self.text)
        return parts


def render_rules(rules=RULES):
    return "Rules:\n" + "\n".join("- " + r for r in rules)


def render_schema(tables, chosen=None):
    """Schema block. `chosen` narrows it to a table set, which is the retrieval path.

    Rendered by `catalog.render_all` rather than by a second renderer here, so the
    number in the prompt and the number day 2 published cannot drift apart.
    """
    if chosen is not None:
        tables = tuple(t for t in tables if t.name in chosen)
        if not tables:
            raise ValueError("table selection is empty, refusing to build a schema-less prompt")
    return "Schema:\n" + catalog.render_all(tables)


def build(question, tables, chosen=None, rules=RULES, correction=""):
    if not question or not question.strip():
        raise ValueError("refusing to build a prompt with no question")
    return Prompt(
        preamble=PREAMBLE,
        rules=render_rules(rules),
        schema=render_schema(tables, chosen),
        question="Question: " + question.strip(),
        correction=correction or "",
    )
