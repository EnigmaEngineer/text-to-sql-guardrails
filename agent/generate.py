"""Generation, and the honest state of it.

**No language model is reachable from the environment this repo is built in.** There is
no API key and no local weight file, so nothing here has ever called one. Rather than
write a client that has never been run and let the tests imply it works, the model is
behind an interface with two implementations that are real and one that refuses.

    ScriptedGenerator   replays SQL recorded against a question. Exercises the pipeline.
    RefusingGenerator   answers CANNOT_ANSWER to everything. The other end of the range.
    NotConfigured       what you get when no backend is set. Raises and says why.

What this buys is that the rest of the agent can be built and tested today, which is the
part the project is actually about. The prompt goes in and text comes out. The text is
parsed and the gate judges it. The warehouse runs it and the answer is compared to gold.
Every step of that is real. Only the middle is a fixture.

What it does not buy is an accuracy number. **A score produced with ScriptedGenerator is
a statement about this file and not about any model.** Day 7 needs a real backend before
it can report accuracy, and that is tracked rather than assumed.

TODO(day7): wire a real backend. Blocker is that the scheduled sandbox has no model
access of any kind, so this has to be run on Syed's laptop with a key in the environment.
Until then no accuracy figure in this repo means anything about a model.
"""

import re

from agent.prompt import CANNOT_ANSWER

# Models wrap SQL in a fenced block more often than not, and the fence is not SQL. This
# matches an opening fence with an optional language tag on its own line.
FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*\n(.*?)\n\s*```\s*$", re.DOTALL)


class GeneratorError(Exception):
    pass


def parse(raw):
    """Turn model text into ("sql", query) or ("cannot_answer", "").

    The refusal token is compared after stripping and after fence removal, because a
    model that has been told to reply with one word will still sometimes put it in a
    code block.
    """
    if raw is None:
        raise GeneratorError("generator returned None")
    text = raw.strip()
    match = FENCE.match(text)
    if match:
        text = match.group(1).strip()
    if not text:
        raise GeneratorError("generator returned an empty string")
    if text.rstrip(".").strip() == CANNOT_ANSWER:
        return "cannot_answer", ""
    return "sql", text


class Generator:
    name = "generator"

    def generate(self, prompt_text):
        raise NotImplementedError


class ScriptedGenerator(Generator):
    """Replays recorded output. A fixture for the pipeline, never a system under test.

    Keyed by question text rather than by prompt text on purpose. A prompt changes every
    time the schema or the rules change, and a fixture that breaks on an unrelated
    reword is a fixture people delete.
    """

    name = "scripted"

    def __init__(self, by_question, strict=True):
        self.by_question = dict(by_question)
        self.strict = strict

    def generate(self, prompt_text):
        question = question_of(prompt_text)
        if question in self.by_question:
            return self.by_question[question]
        if self.strict:
            raise GeneratorError("no scripted answer for %r" % question)
        return CANNOT_ANSWER


class SequenceGenerator(Generator):
    """Replays a list of answers per question, one per call. Written for day 6.

    `ScriptedGenerator` cannot exercise a retry loop and that is not a small point. It is
    keyed by question, so the second call returns whatever the first call returned. A loop
    tested only with it sends a correction and gets the identical query back. The same
    layer then refuses it for the same reason. Every assertion still passes and the
    correction was never read by anything.

    So the fixture had to be able to answer differently on the second call before the
    loop could be tested at all. It still reads no correction. Nothing here is a model
    and nothing here reacts to what it was told. What this buys is that the loop, the
    trace and the stopping rules are exercised on real refusals from real layers. What it
    does not buy is any evidence that a correction helps, and no number in this repo
    claims otherwise.

    Running past the end returns the last answer forever rather than raising. That is
    what makes the repeat rule testable, since a generator that runs out is exactly a
    generator that has stopped responding to correction.
    """

    name = "sequence"

    def __init__(self, by_question):
        self.by_question = {q: list(v) for q, v in by_question.items()}
        self.calls = {}

    def generate(self, prompt_text):
        question = question_of(prompt_text)
        if question not in self.by_question:
            raise GeneratorError("no scripted sequence for %r" % question)
        answers = self.by_question[question]
        if not answers:
            raise GeneratorError("empty sequence for %r" % question)
        i = self.calls.get(question, 0)
        self.calls[question] = i + 1
        return answers[min(i, len(answers) - 1)]


class RefusingGenerator(Generator):
    """Says it cannot answer, always.

    Worth having as a real object. It is the floor for any accuracy measurement, and it
    is the only way to check that a refusal path works when no model is available to
    produce a genuine one.
    """

    name = "refusing"

    def generate(self, prompt_text):
        return CANNOT_ANSWER


class NotConfigured(Generator):
    name = "not_configured"

    def generate(self, prompt_text):
        raise GeneratorError(
            "no generator backend is configured. This repo has never called a model, "
            "see the module docstring and the README limitations section."
        )


# Anchored on the blank line that separates prompt sections, not on the bare word. The
# first version of this used the bare marker and a question reading "What does Question:
# mean in the ticket table?" came back as "mean in the ticket table?". The fixture that
# caught it was written because a marker that can appear in the payload is the obvious
# thing to get wrong.
QUESTION_MARKER = "\n\nQuestion: "


def question_of(prompt_text):
    """Pull the question back out of a built prompt.

    The question is the last section, so everything after the last section boundary is
    it. A question that itself contains a blank line followed by "Question: " would
    still split in the wrong place. That is not defended against, because the eval set
    is one line per question and a defence with no case behind it is decoration.
    """
    idx = prompt_text.rfind(QUESTION_MARKER)
    if idx < 0:
        raise GeneratorError("prompt has no question marker")
    return prompt_text[idx + len(QUESTION_MARKER):].strip()
