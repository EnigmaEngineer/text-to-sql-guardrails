"""Tiny test harness. No pytest.

Deliberate. On an earlier project two pytest style files entered a repo whose runner
loops over plain scripts. One executed zero assertions and exited 0. Having one runner
and one convention means a test file that does not run is visible immediately.
"""


class Failure(AssertionError):
    pass


def eq(got, want, what=""):
    if got != want:
        raise Failure("%s: got %r, wanted %r" % (what or "value", got, want))


def true(cond, what=""):
    if not cond:
        raise Failure("%s: expected true" % (what or "condition"))


def raises(fn, message_fragment, what=""):
    """Assert the message, not just the type.

    Carried in from 08-02, where a test asserted that a function raises ValueError on a
    zero. The language raised ValueError by itself and deleting the guard changed
    nothing. Matching on the message is what makes the guard falsifiable.
    """
    try:
        fn()
    except Exception as exc:
        if message_fragment.lower() not in str(exc).lower():
            raise Failure(
                "%s: raised %s(%s), which does not mention %r"
                % (what or "call", type(exc).__name__, exc, message_fragment)
            )
        return exc
    raise Failure("%s: did not raise at all" % (what or "call"))
