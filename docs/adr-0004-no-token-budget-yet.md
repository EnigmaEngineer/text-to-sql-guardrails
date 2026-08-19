# ADR 0004: No token budget until the model is chosen

Status: accepted

## Context

The retrieval layer builds schema retrieval so that only relevant tables enter the prompt. The natural
The obvious move is to set a token budget for the schema block and build towards it.

That is the exact mistake made on an earlier project of mine, where a 512 token
chunk budget was fixed before choosing the model that would tokenise it. A budget in
tokens is meaningless until the tokeniser is known.

## Decision

Measure the schema in characters and set no token budget.

Measured by `scripts/check_gold.py`.

| what | value |
|---|---|
| tables | 18 |
| columns | 111 |
| whole schema rendered for a prompt | 2,716 chars |
| largest single table rendering | 237 chars |

## Consequences

2,716 characters is small. On most tokenisers that lands somewhere under a thousand
tokens, which means the whole schema fits in a prompt and retrieval would be
solving a problem this warehouse does not have.

That is worth saying plainly rather than hiding. The retrieval layer is being built
against a warehouse where it is not yet needed. The retrieval layer has to either widen the warehouse
until retrieval earns its place, or state that the layer is there for the wide case and
measure what it costs on the narrow one. Building it and quietly implying it was necessary
is the outcome this record exists to prevent.
