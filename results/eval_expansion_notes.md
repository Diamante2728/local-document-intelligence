# Expanded multi-doc eval set — how it was built and why

`eval/multidoc_expanded.json` — 35 hand-authored multi-doc questions. **Awaiting review before
any training data is generated** (Phase 2A Step 0 gate).

## Why this set exists

Stage 1's multi-doc sample cannot measure a fine-tuning effect:

| set | multi-doc questions | one question is worth |
|---|---|---|
| `gold_set.json` | 4 | 25 points |
| `holdout_set.json` | 1 | **100 points** |

At n=1, any result is a coin flip. Building 500 training examples to move a metric that cannot be
read would be wasted effort, and any reported "improvement" would be indistinguishable from noise.

## Why n=35

Large enough that a single question is worth **~2.9 points**, so a real effect separates from
noise. Small enough that every question could be **hand-authored against verified source text**
rather than machine-generated — the eval set is the yardstick, and generating it with the same
class of model being evaluated would be circular. 35 also yields 5–16 questions per operation
family, enough to break results out by operation in 2C(i).

## Composition

| | count |
|---|---|
| **cross-document (≥2 distinct docs)** | **26** |
| same-document controls | 9 |
| distinct documents used | 12 of 16 |

| operation | count |
|---|---|
| comparison | 16 |
| aggregation | 8 |
| lookup_then_combine | 6 |
| contradiction | 5 |

**The 9 same-document controls are deliberate, not filler.** If the fine-tune improves
cross-document questions but leaves these flat, the gain is specific to *multi-document
reasoning* rather than to two-fact extraction in general. Without controls we could not tell
those apart, and would risk claiming a multi-doc win that was really a generic formatting win.

## A design error I made and corrected

The first draft had **only 7 of 35 questions spanning two or more documents.** The other 28
paired two facts drawn from the *same* document — which does not test multi-doc reasoning at all,
and would have produced a meaningless before/after. Caught by a composition check on my own
output before review, and rebuilt to 26 cross-document. Recorded because the first version would
have looked fine on a casual read and measured the wrong thing.

## Contamination control

Freshness is enforced at the **fact level**, not the document level. With a 16-document corpus,
document reuse is unavoidable; reusing the same *figures* is not.

**Method (a) — text overlap.** Normalised token 5-gram Jaccard of every new question against all
29 existing eval questions (20 gold + 9 held-out).

```
highest observed similarity : 0.143   (X02 vs P02)
threshold                   : 0.60
questions above threshold   : 0
```

**Method (b) — answer-figure reuse.** For each new question, the set of figures it requires was
compared against the figures every existing eval question requires. Where a figure is reused
(e.g. FDIC's `64.2`), it is always **paired with a fresh figure from a different document**, so
the question cannot be answered from memory of the earlier item. The Stage 1 gold set draws FDIC
net income `64.2`; this set draws FDIC `1.08` (ROA), `3.17` (NIM), `4,568`, `22.5`, `4.3`, `0.61`,
`1.36` — figures no earlier question uses.

**Method (c) — dependency flagged for Step 2.** The training data generated in Phase 2A Step 2
must also be checked *against this set*, in the other direction. That check cannot run until the
training data exists; it is a required step there, not an omission here.

## Ground-truth verification

Every expected figure was checked to appear in the text of its own cited source page:

```
verified 35 questions against cited source pages
ALL expected figures found in their cited source pages
```

No value came from the SQLite store — the store is the artifact under test, so using it as its own
answer key would be circular and would silently bless extraction defects (the same discipline
applied to Stage 1's gold set).

## Scoring

`answer_contains` requires the figures from **all** cited documents. A response that answers
correctly from only one source scores as a miss — which is precisely the M01/M02/M03 failure
mode this set exists to measure.
