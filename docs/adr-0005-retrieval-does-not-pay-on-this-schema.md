# ADR 0005: Retrieval is kept, off by default, and its prize is measured

Status: accepted

## Context

`adr-0004` measured the whole schema at 2,716 characters and said this layer had to do one of
two things. Widen the warehouse until retrieval earns its place, or state that the layer
is for the wide case and measure what it costs on the narrow one.

The retrieval layer took the second. Widening the warehouse to make a layer look necessary is arranging
the evidence to fit the plan.

## What was measured

Relevance labels come out of the frozen gold SQL rather than out of a hand written list. A
table is relevant to a question when the gold query for that question reads from it. The
tables are pulled from DuckDB's own parse tree, so an alias, a CTE name and the word from
inside a string literal are all handled by the thing that will run the query.

The metric is `complete@k`, the share of questions where every required table was
retrieved. A question needing four tables that gets three is not three quarters right. The
generated SQL cannot be correct at all. So this is a ceiling on end to end accuracy and
not a score.

Measured by `scripts/retrieval_report.py`.

| retriever | k | complete | mean prompt chars |
|---|---|---|---|
| lexical | 8 | 18 of 22 | 1,242 |
| lexical + join | 8 | 21 of 22 | 2,126 |
| dense | 8 | 20 of 22 | 1,298 |
| dense + join | 8 | 20 of 22 | 2,288 |
| send everything | n/a | 22 of 22 | 2,716 |

The same table taken before the plural stripper landed, kept because the comparison between
the two is the point.

| retriever | k | complete | mean prompt chars |
|---|---|---|---|
| lexical | 8 | 13 of 22 | 1,198 |
| lexical + join | 8 | 22 of 22 | 2,193 |
| dense | 8 | 20 of 22 | 1,298 |

## Decision

Keep the layer. Default it off. Record that on this warehouse the most it can win is under
600 characters.

The best configuration gives up one question and saves 590 characters, which the report
prints as 21.7 percent of the whole schema.

That verdict is thinner than it looks and the thinness is the real finding. A four word
plural stripper added to the lexical scorer during this same run moved the best
configuration from 22 of 22 at a saving of 523 characters, where retrieval cost nothing at
all, to 21 of 22 at a saving of 590. Both numbers were produced by
`scripts/retrieval_report.py`, the second of them against a tree with the stemmer reverted.

So whether retrieval is free or costs a question is decided here by an incidental detail
of the baseline. What does not move is the size of the prize. Around 550 characters either
way, on a schema of 2,716. A layer whose maximum benefit is smaller than the noise in how
its baseline handles plurals is not carrying its weight on this warehouse.

The layer stays because the guardrails downstream need a table set to validate
against, and because a wide warehouse is the case the project is written for. What it does
not get is a sentence implying it was necessary here.

## Consequences

The scorecard reports accuracy with the whole schema in the prompt. Retrieval numbers sit beside
it as a separate column, not as the headline.

Two findings are carried forward rather than fixed here.

`dim_date` cannot be retrieved by anything in this repo. Six questions need it and not one
of them contains the word date. Its primary key is `date_key` and the fact tables carry
`order_date_key`, so the naming convention every other join follows breaks on exactly the
dimension that is needed most. Both the text scorers and the join graph miss it for the
same underlying reason, which is that nothing connects the calendar to the question.

Improving the lexical scorer made the combined system worse. Adding a plural stripper took
lexical alone from 13 to 18 questions and took lexical plus join expansion from 22 down to
21. Expansion had been covering for the scorer, and a better scorer put different tables in
the top eight. A component measured alone can improve while the system it sits in gets
worse.
