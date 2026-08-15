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

---

# PRE-REGISTERED CAVEAT — recorded before any training data exists

Written now, before generation and training, so it cannot be mistaken for a post-hoc excuse if
the fine-tune underperforms. Everything below was known or measured **prior** to Step 2.

## 1. Half the known multi-doc failures are out of scope for fine-tuning by construction

From `results/failure_split.md`:

| case | mechanism | LoRA-trainable |
|---|---|---|
| M01 | reasoning — facts in context, model declined | **yes** |
| M02 | reasoning — facts in context, model declined | **yes** |
| M03 | retrieval — FDIC `64.2` absent from filtered context | **no** |
| H09 | routing → retrieval — router bypassed multi-doc entirely | **no** |

LoRA adjusts weights. It changes how a model reasons over the context it is handed; it cannot
change which documents reach that context, nor which path the router selects. **A perfect
fine-tune cannot lift multi-doc past the ceiling M03/H09 impose.**

## 2. The trainable half's proximate cause may not be a model problem at all

Stage 1 diagnosed M01/M02 as follows: the multi-doc path puts the **full compound question**
("Both X and Y describe… what does X report, and what does Y report?") to *each document
separately*. The model therefore sees a question half of which its context cannot answer, and
returns `NOT_IN_CONTEXT` for the whole thing.

That is a **prompt-construction** defect. The obvious repair is to decompose the question per
document before retrieval — plumbing, not weight updates. Fine-tuning is being asked to teach a
model to cope with a badly-shaped prompt rather than fixing the prompt.

## 3. Measured evidence that decomposition also fixes the "untrainable" half

Tested before training, on the doc-filtered retrieval path:

```
case         compound question   decomposed   verdict
M03-FDIC     not retrieved       retrieved    DECOMPOSITION FIXES IT
H09-EPA      not retrieved       retrieved    DECOMPOSITION FIXES IT
M01-BEA      retrieved           retrieved    (failure was reasoning, as diagnosed)
```

This sharpens the picture considerably and corrects our own earlier framing. The M03/H09
retrieval failures are not independent of the compound question — they are **caused by** it. A
40-word question naming two documents produces a diluted query embedding; once filtered to a
single document, the correct chunk no longer ranks. So all four multi-doc failures trace to one
root cause surfacing at two layers:

| | symptom | layer |
|---|---|---|
| M01, M02 | model returns `NOT_IN_CONTEXT` | reasoning |
| M03, H09 | correct chunk never retrieved | retrieval |

## 4. What this means for the verdict, stated in advance

**2C(iii) — the prompted-only baseline — is the deciding test**, not a supporting one. The
comparison is three-armed:

| arm | description |
|---|---|
| 1 | base 3B, current pipeline (compound question per document) |
| 2 | fine-tuned 3B, current pipeline |
| 3 | base 3B **+ per-document decomposition**, no fine-tune |

**A plausible and fully honest outcome is that arm 3 matches or beats arm 2 — i.e. "fine-tuning
was not the right tool here."** We are recording that possibility now, with the mechanism and the
supporting measurement, so that if it happens it reads as a predicted result rather than a
rationalisation.

Arm 3 will be given **genuinely equal effort** to the fine-tune: real few-shot examples and
explicit per-document decomposition of the compound question. A strawman baseline would rig the
comparison in fine-tuning's favour and destroy the value of the test.

## 5. Why we proceed with the fine-tune regardless

The fine-tune, its hyperparameter reasoning, its training curves, and two honestly-documented
training failures are **required Stage 2 deliverables independent of the verdict**. A null or
negative result, measured properly and explained mechanically, is a legitimate deliverable — and
given the analysis above, arguably the more informative one. What would not be legitimate is
discovering this after the fact and presenting it as though it had been anticipated.

## 6. One consequence for the baseline

The pipeline is **deliberately not fixed before training.** Introducing decomposition into the
shared pipeline first would move the baseline mid-experiment and make before/after unreadable.
Decomposition is therefore isolated in arm 3, where it can be measured as its own intervention.
