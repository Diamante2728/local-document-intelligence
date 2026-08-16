# Training data QC report

`data/train_multidoc.jsonl` — **689 examples kept** of 700 generated (621 train / 68 valid).

Generated locally from the SQLite chunk store with `src/train/gen_multidoc.py`. **No cloud API was
used at any point** — facts, context text and question subjects all come from the corpus; sentence
structure comes from local templates.

Auto-generated stats: `data/qc_summary.md` (regenerated each run). This file is the analysis and is
not overwritten by the script — an earlier version of it was clobbered once, which is why the two
are now separate paths.

---

## 1. Rejection rate — and why the headline number is misleading

The shipped run rejects **11 of 700 (1.6%)**. On its own that number is worthless: a gate that
rejects nothing is indistinguishable from a gate that checks nothing. The honest number is the
**trajectory**, because each drop was a real generator or tooling bug that QC caught.

| run | kept | rejected | rate | what QC caught |
|---|---|---|---|---|
| 1 | 108 | 452 | **80.7%** | `degenerate_topic` ×325, `ambiguous_figure` ×169, `answer_lost_figure` ×168 |
| 2 | 465 | 235 | **33.6%** | `ambiguous_figure` ×151, `negative_is_false` ×76 |
| 3 | 688 | 12 | **1.7%** | `ambiguous_figure` ×11 (citation-header numbers) |
| 4 | 699 | 1 | **0.1%** | `ungrounded_figure` ×1 |
| 5 (shipped) | 689 | 11 | **1.6%** | `target_truncated_to_zero` ×9, `target_partly_truncated` ×1 — **found during training, see §4** |

Five defects were found and fixed, all in the generator or the checker rather than by hand-filtering
output:

1. **`answer_lost_figure` ×168 — not a data bug at all.** A false-negative in `src/eval_match.py`,
   the matcher shipped as Fix 1. See §5; it is the most consequential finding here.
2. **Topic extraction emitted a placeholder** instead of failing, producing questions reading
   "state the reported figure and the reported figure". Now returns `None` and drops the fact.
3. **Years used as answer figures.** `2025` is not a measurement — it recurs on nearly every page,
   so it can never be attributed to one excerpt. Same bug class as the Stage 1 router defect, where
   a bare `\d` cue fired on every year.
4. **Citation headers matched as document text.** Doc_ids containing digits
   (`oecd_economic_outlook_116_annex`) made the figure `116` "appear" in every OECD excerpt via its
   label. Grounding now ignores the `[doc pN]` header.
5. **A character proxy standing in for a token budget** — see §4.

## 2. Ablation — proof the gate is not tautological

Because the fixes moved checks *upstream*, QC now has little left to catch. That is correct
engineering (prevention beats detection) but it destroys QC's value as evidence. So the generator
has a `--no-prefilter` flag that disables its guards, and the **same unmodified QC** was run against
an unguarded batch:

| batch | kept | rejected | rate |
|---|---|---|---|
| shipped (guards on) | 689 | 11 | **1.6%** |
| ablation (`--no-prefilter`) | 151 | 549 | **78.4%** |

```
python -m src.train.gen_multidoc --n 700 --no-prefilter --out data/ablation.raw.jsonl
python -m src.train.qc_multidoc --inp data/ablation.raw.jsonl --out /tmp/abl.jsonl --report /tmp/abl.md
```

The gate rejects 78.4% of defective data and 1.6% of clean data. Both numbers are needed.

## 3. Three actual rejected examples — from the ABLATION VALIDATION RUN

**Provenance, stated explicitly.** These three come from the `--no-prefilter` **ablation
validation run** (§2), not from the batch that produced `data/train_multidoc.jsonl`. The shipped
batch rejected 11 examples, all length-related (`target_truncated_to_zero` 9,
`ungrounded_figure` 1, `target_partly_truncated` 1) — those are in `data/qc_rejected.jsonl`.

The raw JSONL records for the three below were overwritten when the shipped QC run rewrote
`data/qc_rejected.jsonl`, and `data/ablation.raw.jsonl` was deleted after the ablation. The text
and reason are preserved verbatim here; reproducing the raw records would require re-running the
seeded ablation. They are shown because the shipped batch's rejections are all one category and
would not illustrate what the gate catches.

### (a) `degenerate_topic` — the question is nonsense

```
QUESTION: Check the USDA WASDE report against the Census housing vacancies report:
          state the reported figure and the reported figure, and flag any discrepancy.
TARGET  : This document gives the reported figure as 672 (p4, the USDA WASDE report)...
```

Topic extraction failed on both halves and fell back to a placeholder, so the question asks for
"the reported figure and the reported figure". This teaches the model to answer questions that name
nothing.

### (b) `ambiguous_figure` — the model cannot learn which excerpt licensed the answer

```
REASON  : 2021 appears in 2 excerpts
TARGET  : According to the Census poverty report (p19), bureau current population survey is 2021.
     excerpt[0] has 2021: False
     excerpt[1] has 2021: True     <- supporting excerpt
     excerpt[2] has 2021: False
     excerpt[3] has 2021: True     <- also contains it
```

The "answer" is a year present in two excerpts. No fact to learn, no attributable source.

### (c) `negative_is_false` — the worst class, and why negatives are checked

```
REASON  : context contains asked figure(s) ['301']
TARGET  : NOT_IN_CONTEXT
     asked figure 2025 present in context: False
     asked figure 301 present in context: True   <- the answer IS there
```

This teaches the model to refuse a question whose answer is in its context — it would *cause* the
M01/M02 behaviour this training set exists to remove.

## 4. The check that passed while the property failed

QC's length check measured **characters** as a proxy for tokens:

```python
MAX_CHARS = 5200   # "~1300 tokens, under the 2048 seq budget with headroom"
```

It reported `0 too_long` and I believed it. During the training smoke run, 8 examples turned out to
have **prompts of 2048+ tokens on their own**. Under `--mask-prompt` with end-truncation, every
assistant target token was cut, producing a `0/0` loss and `NaN`.

| user chars | prompt tokens | chars/token |
|---|---|---|
| 2,812 | 2,278 | 1.23 |
| 3,396 | 2,103 | 1.61 |
| 2,940 | 2,197 | 1.34 |

**Assumed ~2.5 chars/token; the real ratio on this corpus is ~1.33.** Statistical documents are
dense with numerals and table punctuation, which tokenize far more finely than prose.

QC now measures real tokens with the real tokenizer, splitting the failure by severity:
`target_truncated_to_zero` (9) and `target_partly_truncated` (1). Full analysis in
`results/training_issues.md`.

## 5. A false-negative in the matcher shipped as Fix 1

168 examples were rejected as `answer_lost_figure` — the answer supposedly missing a figure the
template guarantees is present. The data was fine; `src/eval_match.py` was wrong.

The boundaries `(?<![\d.])` / `(?![\d.])` reject **any** adjacent period, including a full stop:

```
matches_needle("The rate was 1.3.", "1.3")   -> False    <- correct answer scored WRONG
```

When Fix 1 was reported it was described as **"inflate only, never deflate"** — true of the
substring matcher it replaced, **false of the replacement**, which marks a correct answer wrong
whenever the figure ends a sentence. That is where answers naturally put figures.

Fixed: the boundary now rejects only a genuine numeric continuation — an adjacent digit, or a period
*followed by* a digit. Unit tests extended 14 → 22 cases. **All three eval-set checks re-run under
the corrected matcher; conclusions unchanged** (26/26, 35/35, 0 leaks) via `python -m src.eval_checks`.

## 6. Contamination

Checked against **64 eval questions** across all three sets (20 gold + 9 held-out + 35 multi-doc).

| method | result |
|---|---|
| text — max 5-gram Jaccard vs any eval question | **0.209** (threshold 0.60) → **0 hits** |
| answer figure — training ∩ eval answer figures | **0** overlapping |
| construction-time exclusion | 108 eval figures removed from the fact pool before generation |

Prevented at construction in `gen_multidoc.py`, verified independently in `qc_multidoc.py`. The
chunk-level guard matched nothing — the eval sets do not record `chunk_id` in citations — so it is
reported as **inert**, not as a second passing check.

See `data/diversity_report.md` for the diversity breakdown.
