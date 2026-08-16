# Stage 2 memo — improving multi-document QA on a local model

Apple M1, 8 GB. Everything below ran offline on this machine. No cloud API was used for training,
for synthetic data generation, or for evaluation.

**AI disclosure: see §2 (pre-registration correction) and §8 (four build failures + two measurement
errors).** Full log in `AI_LOG.md`, whose corrections table is at the top of that file.

---

## 1. The headline

I built **689** training examples, fine-tuned Qwen2.5-3B-Instruct with LoRA, and measured the
result three ways against a hand-authored 35-question eval set.

(700 generated, 11 rejected by QC, **689 shipped** = 621 train + 68 validation. An earlier draft
said 699: that was the count after QC run 4, before the token-budget gate added in response to
failure 1 rejected 9 more examples. 689 is the number that was actually trained on.)

**The fine-tune made the system worse, and the reason is that it never trained the skill it was
supposed to train.**

| arm | overall | cross-document (26) | same-doc controls (9) | ARC |
|---|---|---|---|---|
| 1. base 3B | **5/35** | 0/26 | **5/9** | **80.8%** |
| 2. fine-tuned 3B | **2/35** | **2/26** | 0/9 | **2.5%** |
| 3. prompted-only (no training) | **5/35** | **2/26** | 3/9 | 80.8% |

Arm 3 matches or beats arm 2 on every dimension, including an identical cross-document gain.

## 2. The verdict, stated precisely

**This fine-tuning attempt never trained the target skill.** The training data was structurally
single-document throughout: a 20-example random sample found **0 of 20 that ever presented two
documents**, and the generator has no example kind that does. Cross-document combination was never
demonstrated to the model.

What the run produced instead was **general-purpose abstention** — and that single fact explains
every result at once: the cross-document gain (2/26, exactly matching prompting), the collapse of
the same-document controls (5/9 → 0/9), and the ARC regression (80.8% → 2.5%).

**Whether fine-tuning with genuine two-document examples would perform differently remains
untested.**

I want to be explicit that this replaces an earlier, looser claim of mine — "fine-tuning was the
wrong tool here." That framing was pre-registered before training as a plausible outcome, and when
the numbers came in it appeared confirmed. It is not supported. The method was never given the
task. Concluding anything about LoRA's suitability for cross-document reasoning would require
training data containing cross-document reasoning, and this run had none. The pre-registration made
a wrong conclusion *more* tempting, not less, because it let me read a predicted result into
evidence that did not establish it.

## 3. How the training data ended up single-document

The design intent was to target M01/M02, the two Stage 1 multi-doc failures classified as
reasoning-layer and therefore LoRA-trainable (`results/failure_split.md`). Those failures have a
specific shape: the pipeline retrieves **per document**, then puts the **full compound question** to
each document separately, so the model sees a question its context can only half-answer and returns
`NOT_IN_CONTEXT` for all of it.

I built training data that mirrored that shape exactly — one document's excerpts, the whole compound
question, and a target that answers the supported half. That faithfully reproduces the *inference
condition*. It does not contain the *skill*. The model was taught to produce a partial answer from a
single document, roughly 700 times, and it learned that thoroughly.

Three example kinds existed: `first` (260), `second` (263), `negative` (166) — 689 total, of which
negatives are **24.1%**. There was no kind where one document supports **both** halves. So "always disclaim the other half" was never
contradicted by a counter-example, and the model generalised it into an unconditional rule.

## 4. What broke, mechanically

**Same-document controls, 5/9 → 0/9.** The controls are exactly the missing case.

```
X28 — both figures are in ONE document
BASE : "rental vacancy rate ... was 6.6 percent, and the homeowner vacancy rate was 0.8 percent."  ✓
TUNED: "6.6 — ... Nothing in these excerpts addresses homeowner vacancy rates..."                   ✗
```

The homeowner rate is in those excerpts. The model disclaimed a fact it could see.

**ARC, 80.8% → 2.5% — output-format collapse, not catastrophic forgetting.** The distinction is
load-bearing and the raw outputs settle it. Of 29 sampled outputs re-generated in full, **zero were
valid multiple-choice answers picking the wrong option**, which is what degraded reasoning looks
like. Instead: 97/120 begin with `NOT_IN_CONTEXT`, and 114/120 contain no extractable choice.

The non-abstaining outputs are document-citation language applied to a task with no documents:

```
'This document gives decomposers as the answer (C). The other parts of the question, such as
 predators, prey, and producers, are not covered by the text provided.'

'This document gives abyssal plains as 10,070 (p. 10). The other part of the question,
 continental slopes, is not covered by the text provided.'
```

ARC items have no documents, no excerpts, no page numbers. The model is citing pages that do not
exist and declining "the other part of the question" on questions with no parts. It overfit a
response pattern hard enough to stop recognising when the pattern does not apply. **Whether the
underlying science knowledge survived is not measured by this suite** — what is measured is that
the model can no longer express it in the required format.

**The 24% genuine negatives probably caused the damage they were designed to prevent.** I included
them so the fine-tune would not *unlearn* abstention, reasoning that losing abstention would trade
one failure class for the worse "confidently wrong" class. The reasoning was sound; the guard was
aimed at the wrong boundary. The risk was never too little abstention — it was abstention becoming
unconditional.

**The multi-doc eval could not have caught the ARC failure.** `answer_prose()` intercepts
`NOT_IN_CONTEXT` and rewrites it before the numeric fallback, so the behaviour is invisible inside
the pipeline. Only the regression suite exposed it. That is the argument for running one even when
the headline metric looks fine.

## 5. Arm 3 has the same defect, weakly — which locates the real cause

Prompted-only also drops controls (5/9 → 3/9), because its few-shot examples teach the same
"answer one half, disclaim the other" framing. Same mechanism, far milder, because a prompt can be
overridden by context and weights cannot.

That points at the root cause being **how I framed the task**, not the method used to teach it.
Both interventions taught "always partial-answer." The correct framing is conditional: answer
everything this document supports, and disclaim only what it genuinely lacks. Neither the training
data nor the few-shot block expressed that condition, because every example in both was a case
where the document genuinely supported only one half.

## 6. What none of it fixed

`aggregation` **0/8** and `lookup_then_combine` **0/6** in every arm. No intervention tested here
touches them.

## 7. Numbers I am not overstating

- **Multi-doc eval, n=35.** One question is worth 2.9 points. The cross-document deltas here are
  2 questions.
- **Stage 1 regression, n=8 per type.** One question is worth 12.5 points. Numeric shows
  `+0.0%`, but that is **N03 gained and N04 lost** — two of eight answers changed and netted zero.
  It is not "no effect."
- **Validation loss is not evidence.** `valid.jsonl` shares a generator with `train.jsonl`, so a
  falling validation loss shows only that the model learned the *generated* format, which was never
  in doubt. The figure carries that caveat in its own legend. For the record, the series ends at
  **0.120 at iter 800**; its minimum was **0.057 at iter 700**. An earlier draft of this memo cited
  0.057 as though it were the final value — it is the best point, not the last one, and at
  `--val-batches 12` (12 of 68 sequences) the two are not distinguishable from noise anyway.
- **ARC 0.0% was wrong and I reported it.** See §8.

## 8. What went wrong while doing this

Four failures, documented in `results/training_issues.md` as they happened. Two were required; I am
reporting four because trimming to the requested count would misrepresent the run.

1. **NaN loss.** My QC measured **characters** (5,200) as a proxy for a 2,048-**token** budget,
   assuming ~2.5 chars/token. The real ratio on this corpus is **~1.33** — statistical documents are
   dense with numerals and table punctuation. Nine examples had prompts over budget, so
   `--mask-prompt` plus end-truncation left zero target tokens → 0/0 → NaN. Verified it drives all
   56 adapter tensors to NaN.
2. **30 weight updates called 3 epochs.** `--iters` counts batches, not optimizer steps. Caught
   mid-run from an implausible token counter. A weak adapter would have been indistinguishable from
   the "fine-tuning doesn't help" conclusion I had already written down.
3. **Evaluation thrashed swap.** MLX's buffer cache grows unbounded across varying sequence
   lengths; the process reached 7.8 GB on an 8 GB machine. This turned out to be downstream of #4.
4. **An entire arm ran on the wrong model.** A Python default-argument binding bug meant
   `MODEL_ID` reassignment did nothing, so arm 1 ran the **7B**. I had already reported those
   numbers with a breakdown and an interpretation, and had to retract them. It surfaced only because
   a 3B adapter physically cannot load onto 7B weights. **Without the fine-tuned arm, arms 1 and 3
   would both have run on the 7B and produced entirely plausible numbers.**

And two measurement errors in my own instruments:

- **The grader I shipped in Stage 2 had a false negative.** `"The rate was 1.3."` failed needle
  `1.3`, because my boundary rejected a sentence-final period. I had described that fix as "inflate
  only, never deflate" — true of the substring matcher it replaced, false of my replacement.
- **The ARC 0.0% was a harness artefact.** The 8-token generation budget truncated the fine-tuned
  model's answers before they could be scored. Re-run at 64 tokens for both arms: base
  **97/120 unchanged** (the control — the budget change did not inflate the baseline), tuned
  **3/120 = 2.5%**. The honest figure is 2.5%, not 0.0%. The qualitative finding stands; the number
  I first reported did not.

The common shape across all of these: an instrument reported success while the quantity it stood
for was broken. Characters for tokens. Batches for optimizer steps. A stale constant for a model
identity. A truncated generation for an answer. Each was caught by looking at a raw counter and
asking whether its magnitude was physically plausible — not by re-reading the code.

## 9. What I would do next

1. **Add the missing example kind** — one document supporting both halves, target answers both.
   This is the single change most likely to fix the control and ARC regressions, and it is required
   before any claim about LoRA's suitability can be made.
2. **Re-run the comparison with that data.** Only then is "can fine-tuning teach this?" actually
   tested.
3. **Ship prompting in the meantime.** It delivers the full measured benefit today at no training
   cost, no adapter, and no regression risk.
4. **Measure whether ARC knowledge survived**, by scoring log-likelihood over the answer options
   rather than requiring a generated letter. That separates "cannot express" from "does not know" —
   a distinction this suite cannot currently make.

## 10. Artifacts

| file | what |
|---|---|
| `results/stage2_comparison.md` | three-arm results, per operation and cross-doc vs controls |
| `results/training_issues.md` | the four failures, recorded as they happened |
| `results/arc_collapse_analysis.md` | raw ARC outputs, both token budgets |
| `results/failure_split.md` | M01/M02 vs M03/H09 split, plus the 20-example sampling |
| `results/training_curve.png` / `.json` | loss curves, with the val-loss caveat on the figure |
| `results/train_config.md` | hyperparameters, reasoning, and the corrections made to them |
| `data/qc_report.md` | QC trajectory, ablation, rejected examples with provenance |
| `data/diversity_report.md` | six-axis diversity and contamination against all 64 eval questions |
| `results/adapters/multidoc_r8/` | the adapter and its checkpoints at 200/400/600/800 |
| `AI_LOG.md` | full disclosure log, including corrections to claims already reported |
