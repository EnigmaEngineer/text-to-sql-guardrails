"""The eval set is frozen. Questions do not change after the first system runs.

Carried in from the 07-28 decision on an earlier project. Moving a label or deleting a
question after seeing a score is the one action that makes an eval set meaningless, and
it is very easy to do by accident while "cleaning up".

The hash in FROZEN.json is written once. After that a mismatch is an error and the fix
is to revert the questions file, not to refresh the hash.

Freezing is allowed only when every gold query returns at least one row. An empty gold
answer is scored correct by any query that returns nothing, so it measures nothing.
"""

import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN = os.path.join(HERE, "FROZEN.json")
QUESTIONS = os.path.join(HERE, "questions.jsonl")


def digest(path=QUESTIONS):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def read_frozen(path=FROZEN):
    with open(path) as fh:
        return json.load(fh)


def verify(questions_path=QUESTIONS, frozen_path=FROZEN):
    """Raise if the questions file has moved since it was frozen."""
    rec = read_frozen(frozen_path)
    actual = digest(questions_path)
    if actual != rec["sha256"]:
        raise ValueError(
            "eval set has changed since it was frozen on %s.\n"
            "  frozen sha256 %s\n"
            "  actual sha256 %s\n"
            "Revert questions.jsonl. Do not refresh this hash."
            % (rec["frozen_on"], rec["sha256"], actual)
        )
    return rec


def write_frozen(frozen_on, n_questions, n_answerable, note, path=FROZEN,
                 questions_path=QUESTIONS):
    rec = {
        "frozen_on": frozen_on,
        "sha256": digest(questions_path),
        "questions": n_questions,
        "answerable": n_answerable,
        "note": note,
    }
    with open(path, "w") as fh:
        json.dump(rec, fh, indent=2)
        fh.write("\n")
    return rec
