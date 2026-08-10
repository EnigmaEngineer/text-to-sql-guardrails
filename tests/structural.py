"""Detectors that read the code instead of running it.

`ot-034`. `tests/test_guard.py` carries a check that generated SQL can only reach the
database through one door. Nothing tested that check. A mutant that pulled its teeth out
survived the whole suite, which is what you would expect, because a test is not itself
under test. The behaviour was confirmed by hand instead, by adding a real second door to
the pipeline and watching seven checks go red. That worked once and the suite cannot
repeat it.

So the detectors live here as plain functions over a path, and `tests/fixtures/` holds
small modules with defects planted in them on purpose. The detector is then a thing with
its own passing tests, and the manual demonstration becomes a check that runs every time.

Every detector raises `NothingToCheck` rather than returning a clean empty result. Four
checks in this program have already passed by looking at nothing. `prose_check.py`
reported clean on a repo path that did not exist. The day 3 gate approved a string of
semicolons that parsed to zero statements. `depcheck.py` printed a total across zero
repos and exited 0. The day 4 validator found no base tables in a query that read the
host filesystem and reported no problem. A detector that answers "nothing wrong here"
when it was handed nothing is the fifth one waiting.
"""

import ast
import os


class NothingToCheck(Exception):
    """The detector was given no input. That is a finding and not a pass."""


def python_files(directory):
    """Module name and path for every `.py` file directly under `directory`."""
    if not os.path.isdir(directory):
        raise NothingToCheck("not a directory: %s" % directory)
    out = []
    for name in sorted(os.listdir(directory)):
        if name.endswith(".py"):
            out.append((name, os.path.join(directory, name)))
    return out


def execute_offenders(directory, door="guard.py"):
    """Find `.execute()` calls outside the door that are handed something non literal.

    A string literal cannot be model output. So an offender is a structural statement
    that generated SQL has a second route to the connection, and the empty list is a
    statement that it has one.

    Returns the offenders as `file:line` strings and the number of files actually read,
    because a gate has to report what it looked at.
    """
    files = python_files(directory)
    if not files:
        raise NothingToCheck("no python modules under %s" % directory)

    door_alias = door[:-3] if door.endswith(".py") else door
    offenders = []
    scanned = 0
    for name, path in files:
        if name == door:
            continue
        scanned += 1
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "execute":
                continue
            # `guard.execute(...)` is the door itself, not a way round it.
            if isinstance(func.value, ast.Name) and func.value.id == door_alias:
                continue
            first = node.args[0] if node.args else None
            if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                offenders.append((name, node.lineno))

    if scanned == 0:
        raise NothingToCheck(
            "only the door %s is under %s, so nothing was checked" % (door, directory)
        )
    # Sorted on the line as a number. Sorting the formatted string puts line 20 above
    # line 9, which a mutation run found and which reads as a bug in a report.
    return ["%s:%d" % pair for pair in sorted(offenders)], scanned


def called_attribute_names(path):
    """Every `object.attribute(...)` call in a file, as `object.attribute` strings.

    Used to pin which module a caller reaches for. Reading the import list is not
    enough, because importing something and calling it are different acts.
    """
    if not os.path.isfile(path):
        raise NothingToCheck("not a file: %s" % path)
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=os.path.basename(path))
    names = {
        node.func.value.id + "." + node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    }
    if not names:
        raise NothingToCheck(
            "no qualified calls in %s, so an absence check here proves nothing" % path
        )
    return names
