# Stage 2C — three-arm comparison

All arms run the **same** `Qwen2.5-3B-Instruct-4bit` base, so the only difference is the intervention. The multi-doc path is forced for every question: all 35 are known multi-doc, and routing errors are not LoRA-trainable (`results/failure_split.md`), so including them would confound the variable under test.

## (i) Hand-authored eval set — the only real measure

| arm | strict accuracy | partial credit | mean latency |
|---|---|---|---|
| 1. base 3B (pipeline unchanged) | **5/35 (14.3%)** | 0.200 | 47s |
| 2. fine-tuned 3B (LoRA r8) | **2/35 (5.7%)** | 0.286 | 39s |
| 3. base 3B + decomposition + few-shot | **5/35 (14.3%)** | 0.314 | 38s |

*Strict* = every required figure present. *Partial* = mean fraction of required figures present; it separates "moved from 0 to 1 of 2 figures" from "changed nothing", but only strict accuracy answers the question that was asked.

### Cross-document vs same-document controls

| arm | cross-document (26) | same-doc control (9) |
|---|---|---|
| 1. base 3B (pipeline unchanged) | 0/26 (0.0%) | 5/9 (55.6%) |
| 2. fine-tuned 3B (LoRA r8) | 2/26 (7.7%) | 0/9 (0.0%) |
| 3. base 3B + decomposition + few-shot | 2/26 (7.7%) | 3/9 (33.3%) |

The controls exist to tell a *multi-document reasoning* gain apart from a generic two-fact-extraction gain. A win on cross-document that leaves controls flat is the former; a win on both is the latter.

### By operation

| arm | aggregation | comparison | contradiction | lookup_then_combine |
|---|---|---|---|---|
| 1. base 3B (pipeline unchanged) | 0/8 (0.0%) | 4/16 (25.0%) | 1/5 (20.0%) | 0/6 (0.0%) |
| 2. fine-tuned 3B (LoRA r8) | 0/8 (0.0%) | 2/16 (12.5%) | 0/5 (0.0%) | 0/6 (0.0%) |
| 3. base 3B + decomposition + few-shot | 0/8 (0.0%) | 4/16 (25.0%) | 1/5 (20.0%) | 0/6 (0.0%) |

## (ii) Regression — did the adapter damage anything else?

### ARC (general reasoning, unrelated to this corpus)

Measured at `max_tokens=64` for **both** arms, with an identical answer extractor.

| split | base | fine-tuned | delta |
|---|---|---|---|
| ARC-Challenge | 46/60 (76.7%) | 0/60 (0.0%) | **-76.7%** |
| ARC-Easy | 51/60 (85.0%) | 3/60 (5.0%) | **-80.0%** |
| OVERALL | **97/120 (80.8%)** | **3/120 (2.5%)** | **-78.3%** |

### The first ARC measurement was invalid — 0.0% was a harness artefact

The original run used `max_tokens=8`. That suffices for the base model, which replies with a bare
letter, but not for the fine-tuned model, whose replies run 20-40+ tokens and place any letter
mid-sentence. Answers were being cut off before they could be scored.

| | 8-token run | 64-token re-run |
|---|---|---|
| base | 97/120 (80.8%) | **97/120 (80.8%)** |
| fine-tuned | 0/120 (0.0%) | **3/120 (2.5%)** |

**The base score is identical across both budgets**, which is the control: raising the budget did
not inflate the baseline, so the change in the tuned arm is a property of the tuned model and not
of the harness. The honest figure is **2.5%**, not 0.0%.

### This is output-format collapse, not catastrophic forgetting

The distinction matters and the raw outputs settle it. Of 29 sampled fine-tuned outputs
re-generated in full, **0 were valid multiple-choice answers that picked the wrong option** — the
signature of degraded reasoning. Instead:

```
  output starts with NOT_IN_CONTEXT     97 / 120
  no extractable choice at all         114 / 120
  any letter extracted                   6 / 120   (3 right, 3 wrong)
```

and the non-abstaining outputs are document-citation language applied to a task with no documents:

```
'This document gives decomposers as the answer (C). The other parts of the question, such as
 predators, prey, and producers, are not covered by the text provided.'

'This document gives abyssal plains as 10,070 (p. 10). The other part of the question,
 continental slopes, is not covered by the text provided.'

'According to the problem, HIV infects helper T cells (A). These cells are part of the immune
 system that is compromised when HIV is present.'
```

ARC items contain no documents, no excerpts and no page numbers. The model is citing pages that do
not exist and declining to answer "the other part of the question" on questions that have no parts.
It overfit a response pattern hard enough that it no longer recognises when the pattern does not
apply. Whether the underlying science knowledge survives is **not** measured by this suite — what is
measured is that the model can no longer express it in the required format.

### Stage 1 prose / numeric questions (real pipeline)

| type | base | fine-tuned | delta |
|---|---|---|---|
| numeric | 1/8 (12.5%) | 1/8 (12.5%) | **+0.0%** |
| prose | 6/8 (75.0%) | 5/8 (62.5%) | **-12.5%** |
| OVERALL | 7/16 (43.8%) | 6/16 (37.5%) | **-6.2%** |

**n=8 per type. One question is worth 12.5 points**, so every delta in this table is one or two
questions and none of them is separable from noise at this sample size.

Per-question movement, which the aggregate hides:

| question | type | base | tuned | |
|---|---|---|---|---|
| N03 | numeric | wrong | **right** | gained |
| N04 | numeric | **right** | wrong | lost |
| P05 | prose | **right** | wrong | lost |
| other 13 | — | unchanged | unchanged | |

The numeric row is **not** "no effect": it is one question gained and one lost, netting zero. Two
of 8 numeric answers changed. Reporting `+0.0%` alone would imply the adapter left the numeric
path untouched, which is not what happened.

## (iii) Verdict

- base **14.3%** · fine-tuned **5.7%** · prompted-only **14.3%**

**This fine-tuning attempt never trained the target skill.** The training data was structurally
single-document throughout — a 20-example random sample found **0 of 20 examples that ever
presented two documents**, and the generator has no example kind that does. Cross-document
combination was therefore never demonstrated to the model. What the run produced instead was
**general-purpose abstention**, which explains both results at once: the cross-document gain
(2/26, exactly matching prompting) and the control and ARC regressions.

**Whether fine-tuning with genuine two-document examples would perform differently remains
untested.**

This replaces the earlier framing, "fine-tuning was the wrong tool here." That claim is not
supported by what was run. The method was never given the task: every training example showed one
document and asked the model to answer half a question. A conclusion about whether LoRA can teach
cross-document reasoning would require training data that contains cross-document reasoning, and
this run did not have any.

What *is* supported: **prompted-only decomposition matches the fine-tune's entire measured benefit
at none of its cost** (no training, no adapter, no regression), so on the evidence available the
prompting route is the one to ship.

## Mechanism — why the fine-tune regressed

Not "it didn't help": it actively broke two things, and the reason is a gap in the training data I
constructed.

### 1. It learned "always disclaim one half" as an unconditional rule

The training set had three example kinds: `first` (this document supports half one), `second`
(half two), and `negative` (neither). **It contained no examples where a single document supports
BOTH halves.** That case never appeared in ~700 examples, so the model generalised the pattern to
apply always — including when the second fact is sitting in the excerpts.

The 9 same-document controls are exactly that missing case, which is why they went 5/9 -> 0/9:

```
X28 (control - both figures in ONE document)
BASE : "rental vacancy rate ... was 6.6 percent, and the homeowner vacancy rate was 0.8 percent."  CORRECT
TUNED: "6.6 - ... Nothing in these excerpts addresses homeowner vacancy rates..."                  WRONG
```

The homeowner rate is in those excerpts. The model disclaimed a fact it could see.

### 2. It over-generalised NOT_IN_CONTEXT catastrophically

ARC has no document context at all. The fine-tuned model answers it with:

```
'NOT_IN_CONTEXT'
'NOT_IN_CONTEXT_CONTEXT_CONTEXT_CONTEXT_C'      <- degenerate repetition loop
116 of 120 outputs contained no answer letter at all
```

**80.8% -> 0.0%.** Complete destruction of general multiple-choice reasoning.

This inverts a design decision recorded in `src/train/gen_multidoc.py`. 24% of examples were
genuine negatives whose target is `NOT_IN_CONTEXT`, included specifically so the fine-tune would
not *unlearn* abstention — the reasoning being that destroying abstention would trade one failure
class for the worse "confidently wrong" class. That reasoning was sound and the guard was aimed at
the wrong boundary. The risk was never that the model would abstain too little; it was that it
would abstain **unconditionally**. The negatives are the most likely cause of the damage they were
meant to prevent.

The multi-doc eval could not see this, because `answer_prose()` intercepts `NOT_IN_CONTEXT` and
rewrites it before falling back to the numeric path. **The regression suite is the only reason this
was caught** — which is the argument for running one even when the headline metric looks fine.

### 3. The same damage reaches Stage 1's shipped behaviour

```
P05  BASE : "target range for the federal funds rate at 5-1/4 to 5-1/2 percent since July 2023"   CORRECT
     TUNED: "525 - that is target range per the FOMC maintained..."                               WRONG
N04  BASE : "498.5 billion dollars ... construction and development loans"                        CORRECT
     TUNED: "0.44 - that is construction and development loans ... Nothing in these excerpts..."  WRONG
```

The rigid template overwrites correct prose answers with a mangled figure plus a spurious
disclaimer.

### 4. Arm 3 carries the same defect, far more weakly

Prompted-only also drops controls (5/9 -> 3/9), because its few-shot examples teach the same
"answer one half, disclaim the other" framing. Same mechanism, much milder — a prompt can be
overridden by context, weights cannot.

**That points at the real root cause: the way the TASK was framed, not the method used to teach
it.** Both interventions taught "always partial-answer". The correct framing is conditional —
answer everything this document supports, and disclaim only what it genuinely does not contain.
Neither the training data nor the few-shot block expressed that condition, because every example
in both was a case where the document genuinely supported only one half.

## What none of the three arms fixed

`aggregation` 0/8 and `lookup_then_combine` 0/6 in **every** arm. Whatever those require, no
intervention tested here touches it. Reported because a comparison that only lists what moved is
not an honest account of what was measured.

## Cost comparison

| | fine-tune | prompted-only |
|---|---|---|
| cross-document gain | +2/26 | +2/26 |
| control damage | -5/9 | -2/9 |
| general reasoning (ARC) | **-80.8 points** | none (base model) |
| Stage 1 prose | -12.5 points | none |
| training cost | ~3.1 h on M1 8 GB | none |
| artefact to ship | 26.6 MB adapter | a prompt |
| reversible | retrain | edit a string |

Prompting obtains the entire measured benefit at none of the cost.
