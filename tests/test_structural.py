"""Tests for the detectors in `tests/structural.py`.

This file exists because a check cannot be tested from inside itself. The one door check in `test_guard.py` was the most
important thing static validation produced and it was the only thing in the repo whose behaviour had
never been demonstrated by anything except a person trying it once.

Two halves. The detector must find a defect that is really there, and it must refuse
when it was handed nothing to look at. The second half is the one that keeps being
skipped, here and in the tooling around it.
"""

import os

from tests.harness import eq, raises, true
from tests import structural

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
AGENT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent"
)


def _marked_lines(*relative_paths):
    """Where the fixtures say the defects are.

    Found by searching for the marker rather than written down as numbers, so editing a
    fixture cannot quietly move a defect out from under the assertion.
    """
    out = []
    for rel in relative_paths:
        path = os.path.join(FIXTURES, rel)
        with open(path, encoding="utf-8") as fh:
            for n, line in enumerate(fh, start=1):
                if "# DEFECT" in line:
                    out.append((os.path.basename(rel), n))
    return ["%s:%d" % pair for pair in sorted(out)]


def _line_holding(relative_path, fragment):
    """The one line of a fixture carrying `fragment`, as the detector would report it."""
    path = os.path.join(FIXTURES, relative_path)
    hits = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, start=1):
            if fragment in line:
                hits.append("%s:%d" % (os.path.basename(relative_path), n))
    if len(hits) != 1:
        raise AssertionError("%r appears %d times in %s" % (fragment, len(hits), path))
    return hits[0]


def check_the_detector_finds_every_planted_second_door():
    offenders, scanned = structural.execute_offenders(
        os.path.join(FIXTURES, "second_door")
    )
    want = _marked_lines("second_door/explainer.py", "second_door/counter.py")
    eq(len(want), 4, "the fixtures still carry four markers")
    eq(offenders, want, "offenders")
    eq(scanned, 2, "files read")


def check_the_detector_is_quiet_on_a_package_with_one_door():
    """The clean fixture has a literal `.execute()` in it, which must not be reported."""
    offenders, scanned = structural.execute_offenders(os.path.join(FIXTURES, "one_door"))
    eq(offenders, [], "offenders")
    eq(scanned, 1, "files read")


def check_the_detector_refuses_a_directory_with_no_modules():
    raises(
        lambda: structural.execute_offenders(os.path.join(FIXTURES, "no_modules")),
        "no python modules",
        "empty directory",
    )


def check_the_detector_refuses_when_only_the_door_is_present():
    """Zero files read is not a clean result. It is an absence of evidence."""
    raises(
        lambda: structural.execute_offenders(os.path.join(FIXTURES, "door_only")),
        "nothing was checked",
        "door only",
    )


def check_the_detector_refuses_a_path_that_is_not_there():
    raises(
        lambda: structural.execute_offenders(os.path.join(FIXTURES, "no_such_thing")),
        "not a directory",
        "missing path",
    )


def check_the_door_name_is_what_decides_which_file_is_skipped():
    """Point it at the clean fixture with the wrong door and the door itself offends.

    Worth pinning. The exemption is the one piece of this detector that says "allowed",
    and a detector that exempts the wrong file reports clean forever.
    """
    offenders, scanned = structural.execute_offenders(
        os.path.join(FIXTURES, "one_door"), door="reader.py"
    )
    eq(offenders, [_line_holding("one_door/guard.py", "con.execute(sql)")], "the door")
    eq(scanned, 1, "files read")


def check_call_names_reads_the_object_and_the_attribute_together():
    names = structural.called_attribute_names(
        os.path.join(FIXTURES, "one_door", "reader.py")
    )
    true("guard.execute" in names, "the door call")
    true("con.execute" in names, "the literal call")
    true("guard.approve" not in names, "and nothing it does not call")


def check_call_names_refuses_a_module_that_calls_nothing():
    """Otherwise every "does not call X" assertion passes for free."""
    raises(
        lambda: structural.called_attribute_names(
            os.path.join(FIXTURES, "quiet", "silent.py")
        ),
        "no qualified calls",
        "silent module",
    )


def check_the_real_agent_package_is_actually_being_read():
    """The wiring check. The detector above is only worth having if it runs on agent/.

    A count rather than a presence test, because the failure this guards against is the
    scan quietly reading nothing and reporting clean.
    """
    offenders, scanned = structural.execute_offenders(AGENT_DIR)
    eq(offenders, [], "offenders in agent/")
    true(scanned >= 5, "modules read in agent/: %d" % scanned)
