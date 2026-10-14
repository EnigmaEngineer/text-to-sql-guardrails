# Running the checks

Moved out of the README so the front page stays short. Back to the [README](../README.md).

## Mutation

The test suite is checked by breaking things on purpose, one round per layer as it landed.
The warehouse and eval set, 12 mutants and 11 killed. Retrieval, 14 and 13. The gate, 14 and
13. Validation, 17 and 15, then 14 more over the structural detector and 13 killed. Cost, 15
and 14. The correction loop, 30 over two rounds and all of them killed after six fixes. The
scorecard, 20 and 18, then 22 and all 22.

Every survivor across the week was either a deliberate control, an unreachable branch that
was kept for a stated reason, or a real gap that became a test. Two of them were live
defects in the code of the day that found them.
