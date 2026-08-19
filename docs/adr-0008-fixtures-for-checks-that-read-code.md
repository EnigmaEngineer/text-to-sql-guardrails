# ADR 0008: fixtures for checks that read code

Status: accepted
## Context

Static validation added a check that generated SQL can only reach the database through
`agent/guard.py`. It walks `agent/` with `ast` and fails if any `.execute()` outside the
door is handed something that is not a string literal. It is the single most important
check in the repo, because it is the only one that fails when someone adds a route rather
than when someone breaks a route that exists.

An early mutation run put a mutant through it that removed the string literal test. The
mutant survived. That is not surprising and it is not a bug in the suite. Nothing tests a
test. The behaviour was confirmed by hand instead, by adding a real second door to the
pipeline and watching 7 checks go red.

That confirmation worked once and the suite cannot repeat it. So the most important check
in the repo was, when it was written, the least verified thing in it.

The same shape is coming twice more. A cost ceiling next, then a retry cap, and
both are rules a caller could forget to invoke. An earlier project of mine had the
same problem with a quarantine that only one of two report scripts applied.

## Decision

A check that reads code is written as a plain function over a path, in
`tests/structural.py`, and the code it reads in its own tests is a fixture under
`tests/fixtures/`.

Three rules.

**A fixture carries its defect on a line marked `# DEFECT`.** The test locates those lines
by searching for the marker, never by writing a line number down. Editing a fixture cannot
then quietly move a defect out from under an assertion.

**Nothing under `tests/fixtures/` is ever imported.** The files are parsed as text. One of
them contains the exact defect the guard exists to stop, so importing a fixture would be
importing the bug. The runner collects modules named `test_*` directly under `tests/`, so
a subdirectory is invisible to it.

**A detector raises rather than returning a clean empty result.** If it was handed no
files, that is a finding about its input and not a pass. The same holds for a directory
containing nothing but the door. It holds for a module with no calls in it too. Four
checks in this repo and the tooling around it have
already passed by looking at nothing. `prose_check.py` reported clean on a repo path that
did not exist. The parser gate approved a string of semicolons that parsed to zero
statements. `depcheck.py` printed a total across zero repos. The catalog validator found no
base tables in a query reading the host filesystem and reported no problem.

## Consequences

The manual demonstration became a check that runs every time. A mutation pass over the
detector kills 13 of 14, and the survivor is the control.

Building it found two real defects that the original in-line version had. The string half
of "must be a string literal" was carrying no weight, because no fixture ever passed a
constant that was not a string, so a detector that accepted any constant at all looked
correct. And the report was sorted as text, which put a defect on line 23 above one on
line 9.

The cost is a directory of code that is not the product. It is about 90 lines across six
small files. That is the price of the check having a test, and the alternative is what day
4 had, which is a claim backed by something a person did once.

## What this does not do

A fixture proves the detector reports what it is pointed at. It says nothing about whether
`agent/` is the right thing to point it at. That is why both `test_guard.py` and
`test_structural.py` assert the number of modules actually read, rather than only that the
offender list came back empty.
