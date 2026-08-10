# Fixtures

Small modules with defects planted in them on purpose. `tests/structural.py` reads these
with `ast` and `tests/test_structural.py` asserts what it finds.

**Nothing here is ever imported.** These files are parsed as text. A couple of them
contain code that is deliberately wrong, and one of them contains the exact defect the
guard exists to stop. Importing a fixture would be importing the bug.

The runner will not pick them up. `tests/run_all.py` collects modules named `test_*`
directly under `tests/`, so a subdirectory is invisible to it.

A line carrying a `# DEFECT` comment is one the detector is expected to report. The test
finds those lines by searching for the marker rather than by hard coding a number, so
editing a fixture does not quietly break the assertion.

| Directory | What it is for |
|---|---|
| `one_door/` | A clean package. The detector must stay quiet on it. |
| `second_door/` | Two planted routes to the connection, in two files. |
| `door_only/` | Nothing but the door, so the detector reads zero files. |
| `no_modules/` | A directory with no python in it at all. |
| `quiet/` | A module that calls nothing, for the call name detector. |

The last three exist because a detector handed no input must say so. Returning a clean
empty result is how four separate checks in this program have passed while looking at
nothing.
