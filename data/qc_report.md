# Training data QC report

`data/train_multidoc.jsonl` — **699 examples kept** of 700 generated (630 train / 69 valid).

Generated locally from the SQLite chunk store with `src/train/gen_multidoc.py`. **No cloud API was
used at any point** — facts, context text and question subjects all come from the corpus; sentence
structure comes from local templates.

---

## 1. Rejection rate — and why the headline number is misleading

The shipped run rejects **1 of 700 (0.1%)**. On its own that number is worthless: a gate that
rejects nothing is indistinguishable from a gate that checks nothing. The honest number is the
**trajectory**, because each drop was a real generator bug that QC caught.

| run | kept | rejected | rate | what QC caught |
|---|---|---|---|---|
| 1 | 108 | 452 | **80.7%** | `degenerate_topic` ×325, `ambiguous_figure` ×169, `answer_lost_figure` ×168 |
| 2 | 465 | 235 | **33.6%** | `ambiguous_figure` ×151, `negative_is_false` ×76 |
| 3 | 688 | 12 | **1.7%** | `ambiguous_figure` ×11 (citation-header numbers) |
| 4 (shipped) | 699 | 1 | **0.1%** | `ungrounded_figure` ×1 |

Four defects were found and fixed, in the generator rather than by filtering the output:

1. **`answer_lost_figure` ×168 — not a data bug at all.** It was a false-negative in
   `src/eval_match.py`, the matcher shipped in Fix 1. See §4; it is the most important finding here.
2. **Topic extraction emitted a placeholder** instead of failing, producing questions that read as
   nonsense ("state the reported figure and the reported figure"). Now returns `None` and the fact
   is dropped from the pool.
3. **Years were being used as answer figures.** `2025` is not a measurement — it recurs on nearly
   every page, so it can never be attributed to one excerpt. This is the same bug class as the
   Stage 1 router defect, where a bare `\d` cue fired on every year.
4. **Citation headers were matched as document text.** Several doc_ids contain digits
   (`oecd_economic_outlook_116_annex`), so the figure `116` "appeared" in every OECD excerpt via
   its label. Grounding now ignores the `[doc pN]` header entirely.

## 2. Ablation — proof the gate is not tautological

Because the fixes moved the checks *upstream*, QC now has almost nothing left to catch. That is
correct engineering (prevention beats detection) but it destroys QC's value as evidence. So the
generator has a `--no-prefilter` flag that disables its guards, and the **same unmodified QC** was
run against an unguarded batch:

| batch | kept | rejected | rate |
|---|---|---|---|
| shipped (guards on) | 699 | 1 | **0.1%** |
| ablation (`--no-prefilter`) | 151 | 549 | **78.4%** |

```
python -m src.train.gen_multidoc --n 700 --no-prefilter --out data/ablation.raw.jsonl
python -m src.train.qc_multidoc --inp data/ablation.raw.jsonl --out /tmp/abl.jsonl --report /tmp/abl.md
```

The gate rejects 78.4% of defective data and 0.1% of clean data. Both numbers are needed; either
alone would be misleading.

## 3. Three actual rejected examples

Verbatim from the ablation batch, since the shipped batch has only one rejection.

### (a) `degenerate_topic` — the question is nonsense

```
QUESTION: Check the USDA WASDE report against the Census housing vacancies report:
          state the reported figure and the reported figure, and flag any discrepancy.
TARGET  : This document gives the reported figure as 672 (p4, the USDA WASDE report)...
```

Topic extraction failed on both halves and fell back to a placeholder, so the question asks for
"the reported figure and the reported figure". Training on this teaches the model to answer
questions that name nothing.

### (b) `ambiguous_figure` — the model cannot learn which excerpt licensed the answer

```
REASON  : 2021 appears in 2 excerpts
QUESTION: I need two numbers: draws principally final data from the Fed Survey of Consumer
          Finances, and bureau current population survey from the Census poverty report...
TARGET  : According to the Census poverty report (p19), bureau current population survey is 2021.
     excerpt[0] has 2021: False
     excerpt[1] has 2021: True     <- supporting excerpt
     excerpt[2] has 2021: False
     excerpt[3] has 2021: True     <- also contains it
```

The "answer" is the year 2021, present in two different excerpts. There is no fact here to learn,
and no way for the model to attribute the figure to a source.

### (c) `negative_is_false` — the worst class, and the reason negatives are checked

```
REASON  : context contains asked figure(s) ['301']
QUESTION: Using the USDA agricultural prices report and the Census housing vacancies report
          together, what is the combined picture for agricultural prices september and
          branch public information office?
TARGET  : NOT_IN_CONTEXT
     asked figure 2025 present in context: False
     asked figure 301 present in context: True   <- the answer IS there
```

This example teaches the model to refuse a question whose answer is sitting in its context. It
would *cause* the exact M01/M02 behaviour this training set exists to remove. A rejection rate that
did not catch these would be worse than no QC at all.

## 4. A false-negative in the matcher shipped as Fix 1

168 examples were rejected as `answer_lost_figure` — the answer text supposedly missing a figure
that the template guarantees is present. The data was fine; `src/eval_match.py` was wrong.

The boundaries `(?<![\d.])` and `(?![\d.])` reject **any** adjacent period, including a full stop:

```
matches_needle("The rate was 1.3.", "1.3")   -> False    <- correct answer scored WRONG
```

This matters beyond the training data. When Fix 1 was reported, it was described as
**"inflate only, never deflate"** — true of the substring matcher it replaced, but **not true of
the replacement**, which marks a correct answer wrong whenever the figure ends a sentence. That is
where answers naturally put figures.

Fixed: the boundary now rejects only a genuine numeric continuation — an adjacent digit, or a
period *followed by a digit*. A period followed by a space or end-of-string is punctuation.

```
(?<!\d)(?<!\d\.) <needle> (?!\d)(?!\.\d)
```

Unit tests extended from 14 to 22 cases, including six sentence-final-period regressions.
**All three eval-set checks were re-run under the corrected matcher and their conclusions are
unchanged** (26/26 cross-document dependencies hold, 35/35 verify, 0 partner leaks) — see
`python -m src.eval_checks`, now a committed script rather than an ad-hoc one, precisely because a
matcher change can silently alter what it reports.

## 5. Rejections by reason — shipped run

| reason | n |
|---|---|
| `ungrounded_figure` | 1 |

Full rejected records with reasons: `data/qc_rejected.jsonl`.

## 6. Contamination

Checked against **64 eval questions** across all three sets (20 gold + 9 held-out + 35 multi-doc).

| method | result |
|---|---|
| text — max 5-gram Jaccard vs any eval question | **0.209** (threshold 0.60) → **0 hits** |
| answer figure — training ∩ eval answer figures | **0 of 296** distinct training figures |
| construction-time exclusion | 108 eval figures removed from the fact pool before generation |

Prevented at construction in `gen_multidoc.py`, verified independently in `qc_multidoc.py`. The
chunk-level guard matched nothing — the eval sets do not record `chunk_id` in citations — so it is
reported as **inert**, not as a second passing check. Figure-level exclusion does the real work.

See `data/diversity_report.md` for the diversity breakdown.
