"""What the agent did, in order, across every attempt it made.

I called the trace "the interesting bit" of this project and it is right. A
guardrail that refuses is only useful if someone can see which layer refused and why.

Kept separate from `agent.pipeline` because a trace is a value and the loop is a
procedure. The loop builds one and hands it back. Nothing here decides anything, which
means the renderer can be changed without touching the thing being traced.

`render` returns text rather than HTML. The plan named a viewer and listed Streamlit
among the technologies. There is no browser in the environment this repo is built in, so
a Streamlit app here would be a file nobody has ever run. Text renders in a terminal, in
a log and in a Slack message, and it is checkable by a test. See `docs/adr-0010`.
"""

from dataclasses import dataclass, field

STOPPED_UNRETRYABLE = "stopped_unretryable"
STOPPED_REPEATED = "stopped_repeated"
STOPPED_AT_CAP = "stopped_at_cap"
RESOLVED = "resolved"


@dataclass
class Trace:
    question: str
    max_retries: int = 2
    attempts: list = field(default_factory=list)
    corrections: list = field(default_factory=list)
    ending: str = ""

    @property
    def final(self):
        return self.attempts[-1] if self.attempts else None

    @property
    def outcome(self):
        return self.final.outcome if self.final else ""

    @property
    def retries(self):
        """Attempts after the first. Zero when the first one landed."""
        return max(0, len(self.attempts) - 1)

    def add(self, attempt, correction=None):
        self.attempts.append(attempt)
        self.corrections.append(correction)

    def as_dict(self):
        return {
            "question": self.question,
            "outcome": self.outcome,
            "ending": self.ending,
            "max_retries": self.max_retries,
            "retries": self.retries,
            "attempts": [a.as_dict() for a in self.attempts],
            "corrections": [c.as_dict() if c else None for c in self.corrections],
        }


def render(trace, width=78):
    """One trace as readable text.

    Every attempt shows its steps with the one that failed marked, then the correction
    that was sent or the reason none was. A reader should be able to answer "why did
    this stop" without opening the code.
    """
    lines = []
    lines.append("Q: %s" % trace.question)
    lines.append("=" * width)

    for i, attempt in enumerate(trace.attempts, 1):
        lines.append("")
        lines.append("attempt %d of %d" % (i, trace.max_retries + 1))
        if attempt.sql:
            lines.append("  sql      %s" % _clip(attempt.sql, width - 11))
        for step in attempt.steps:
            mark = "ok  " if step["ok"] else "FAIL"
            lines.append("  %-8s %s  %s" % (step["step"], mark, _clip(step["detail"], width - 20)))
        lines.append("  outcome  %s%s" % (attempt.outcome, _suffix(attempt)))

        correction = trace.corrections[i - 1]
        if correction is None:
            continue
        if correction.action == "stop":
            lines.append("  -> not coached (%s)" % correction.code)
        else:
            lines.append("  -> sent back: %s" % _clip(correction.text, width - 16))

    lines.append("")
    lines.append("ending   %s after %d retry(s)" % (trace.ending, trace.retries))
    return "\n".join(lines)


def _suffix(attempt):
    if attempt.outcome == "refused":
        return " (%s)" % attempt.detail
    if attempt.outcome == "answered":
        return " (%d rows)" % len(attempt.rows)
    return ""


def _clip(text, limit):
    text = " ".join((text or "").split())
    if limit < 4 or len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
