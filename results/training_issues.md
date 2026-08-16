# 2B — what went wrong during training

Recorded **as each failure happened**, with the diagnosis that resolved it. Neither of these was
anticipated; both were found by noticing a number that looked wrong and chasing it, not by a
planned check.

---

## Failure 1 — `Train loss nan`: a character proxy for a token budget

### Symptom

Ten-iteration smoke run, before any real training:

```
Iter 5:  Train loss 4.602, ... Trained Tokens 178, Peak mem 3.871 GB
Iter 10: Train loss nan,   ... Trained Tokens 358, Peak mem 4.606 GB
[WARNING] Some sequences are longer than 2048 tokens. The longest sentence 2610
          will be truncated to 2048.
```

What actually caught my attention was **not** the NaN — it was `Trained Tokens 358`. Ten iterations
at effective batch 8 should have trained on tens of thousands of tokens. A number three orders of
magnitude too small meant something structural was wrong, and the NaN was downstream of it.

### Diagnosis

Three facts, each measured:

1. **`--mask-prompt` means only assistant tokens carry loss.** Assistant targets here are short:
   min 5, median 43, max 63 tokens. So a small "trained tokens" count is expected — but not *that*
   small.
2. **mlx_lm truncates from the END**, which is exactly where the assistant target lives.
3. **8 of 630 training examples had a prompt of 2048+ tokens on their own** — before the answer.

For those 8, truncation to `max_seq_length=2048` removes **every** target token. The loss is
`sum(masked_CE) / n_target_tokens` = `0 / 0` = **NaN**.

Confirmed by isolating them into their own dataset and training on nothing else:

```
Iter 1: Train loss nan, ... Trained Tokens 0, Peak mem 5.951 GB
Iter 4: Train loss nan, ... Trained Tokens 0
-> adapter tensors with NaN: 56 / 56   VERDICT: weights CORRUPTED
```

**The effect is data-dependent, which is what makes it dangerous.** In the concentrated probe all
56 adapter tensors went NaN — the adapter is destroyed. In the mixed smoke run the saved adapter
was *finite* and had genuinely trained (112/112 `lora_b` tensors moved off their zero init), yet
the reported loss was still NaN. So depending on how the bad examples happen to be sampled into
batches, this either silently poisons the weights or merely makes the loss curve unreadable. A
failure whose severity depends on shuffle order is not one to leave in.

### Root cause — the actual mistake

My QC gate did have a length check. It measured the **wrong unit**:

```python
MAX_CHARS = 5200   # "~1300 tokens, under the 2048 seq budget with headroom"
```

That assumed ~2.5 characters per token. Measured on this corpus:

| user chars | prompt tokens | chars/token |
|---|---|---|
| 2,812 | 2,278 | 1.23 |
| 3,396 | 2,103 | 1.61 |
| 2,940 | 2,197 | 1.34 |
| 2,907 | 2,315 | 1.26 |

**Actual ratio ≈ 1.33 chars/token, not 2.5.** Government statistical documents are dense with
numerals, currency symbols, percent signs and table punctuation, all of which tokenize far more
finely than prose. Every one of these examples passed a 5,200-character limit while blowing
through a 2,048-token budget by 250+ tokens.

The check reported "0 too_long" and I believed it. It was measuring a proxy that was off by ~2x in
the direction that hides the problem.

### Fix

QC now measures real tokens with the real tokenizer, and distinguishes two severities:

| check | condition | consequence if unfixed |
|---|---|---|
| `target_truncated_to_zero` | `prompt_tokens >= 2048` | 0/0 → NaN → possible weight corruption |
| `target_partly_truncated` | `prompt+target > 2048` | trained on a half-written answer |

Rejected 9 and 1 respectively. Training data rebuilt: 621 train / 68 valid, every example verified
to fit 2048 tokens *including* its target.

### Why this one matters beyond itself

This is the third time in this project that a **proxy measurement** passed while the real property
failed — after Stage 1's L2 (re-reading extracted text cannot reveal a dropped label) and the
substring grader (reading the matcher cannot reveal what it over-matches). The pattern is now
unmistakable: **if a check does not measure the quantity that actually constrains the system, it
will report success at exactly the moment it matters.** Characters are not tokens.

---

## Failure 2 — I configured 30 weight updates and called it 3 epochs

### Symptom

Caught **mid-run**, 10 iterations in, from a number that did not add up. The log read:

```
Iter 10: Train loss 4.192, ... Trained Tokens 255
```

255 trained tokens after 10 iterations. Assistant targets average ~37 tokens, so 255 tokens is
about **7 sequences** — not the 80 (10 iters × effective batch 8) I expected. The arithmetic only
works if `--iters` counts something other than what I assumed.

### Diagnosis

From `mlx_lm/tuner/trainer.py`:

```python
for it, batch in zip(
    range(1, args.iters + 1),
    iterate_batches(dataset=train_dataset, batch_size=args.batch_size, ...),
):
```

Each `it` consumes **one batch of `batch_size`**. Gradient accumulation does not change how many
batches `--iters` covers — it changes how often `optimizer.update` fires:

```python
if do_update:
    grad = tree_map(lambda x: x / grad_accum_steps, grad)
    optimizer.update(model, grad)
```

So with `batch_size=1`, `--iters 240` means **240 sequences seen**, and with
`--grad-accumulation-steps 8`, **30 optimizer updates**.

| what I wrote in `train_config.md` | what the config actually did |
|---|---|
| "iters 240 ≈ 3 epochs (621 examples / effective batch 8 = 78 steps/epoch)" | **0.39 epochs**, 240 of 621 examples seen once, **30 weight updates** |

I had conflated "iteration" with "optimizer step" and computed epochs as
`iters × accumulation / n_examples` when the correct expression is `iters × batch_size / n_examples`.
The accumulation factor belongs in the *update count*, not the *data-seen* count. I multiplied by it
in exactly the wrong place — which inflated my epoch estimate by precisely the accumulation factor, 8x.

### Why it would have been easy to miss

The run was healthy by every signal I was watching. Loss fell 4.989 → 4.192, memory sat at 4.2 GB,
no warnings. Nothing about a 30-update run looks wrong from the outside; it just produces a weak
adapter, and a weak adapter in 2C is indistinguishable from "fine-tuning does not help on this task"
— which is a conclusion this project has **pre-registered as a plausible outcome**. That is the real
danger: this error would have manufactured evidence for a hypothesis we had already written down,
and it would have been extremely tempting to accept it.

### Fix

Aborted the run (log preserved as `results/train_log_aborted_240iter.txt`) and recomputed:

| iters | accum | epochs | optimizer updates | est. wall clock |
|---|---|---|---|---|
| 240 | 8 | 0.39 | 30 | 0.7 h |
| **800** | **4** | **1.29** | **200** | **~2.3 h** |
| 1863 | 8 | 3.00 | 232 | 5.4 h |

Relaunched at **800 iters, accumulation 4** — 200 optimizer updates, 1.29 epochs. Accumulation was
lowered from 8 to 4 to buy more updates per sequence seen; at 200 updates the adapter gets a real
chance to move, and the effective batch of 4 is still within the normal LoRA range. Three epochs was
rejected on wall-clock grounds (5.4 h) and is recorded here as the tradeoff it is, not hidden.

### The general lesson

Failure 1 was a proxy measuring the wrong unit (characters for tokens). Failure 2 is the same shape
one level up: I used a **derived quantity** (epochs) that I had computed from an assumption about a
framework's semantics, and never checked the assumption against the source. In both cases the
instrument read "fine" while the thing it stood for was broken. The check that caught both was the
same primitive one — *look at a raw counter and ask whether its magnitude is physically plausible*.

---

## Stated limitation — the validation curve cannot resolve small changes

Not a failure, but a limit I built into the run and should not let a reader mistake for signal.

`--val-batches 12` at `batch_size 1` means each validation point is computed on **12 sequences out
of the 68-example validation split**. The observed swing:

```
Iter 200  Val 0.133
Iter 300  Val 0.212     <- looked like overfitting onset
Iter 400  Val 0.091     <- new minimum; the rise was sampling noise
```

At iter 300 I flagged the increase as possible overfitting and deliberately declined to act on it
until iter 400. That was the right call, and iter 400 showed the rise was noise — but the episode
demonstrates the real point: **at n=12, this curve cannot distinguish a genuine 0.05–0.10 change
from sampling variance.** Any narrative built on individual validation points in this run would be
reading noise.

Why it was set that way: each validation pass costs ~70–90 s, and at 8 evaluations across the run a
full 68-example validation would have added ~25 minutes of wall clock on a machine already running
~3.2 h. That was a defensible trade, but it bought speed at the cost of resolution, and the
resolution is what a training curve is *for*.

This does not affect the Stage 2 verdict. 2C evaluates on the full 35-question hand-authored eval
set, which is the only measurement in this project that can show real improvement — validation loss
here selects checkpoints at best, and even that only coarsely.

---

## Failure 3 — the evaluation run thrashed swap and stalled (found in 2C, not 2B)

Recorded here because it invalidated measurements and had to be fixed before any 2C number could
be trusted.

### Symptom

The arm-1 evaluation stopped producing rows. The progress ticker read `base=24/35` twice, twelve
minutes apart — six questions should have completed in that window.

Not an obvious crash: the process was **alive**, but at **1.1% CPU**.

### Diagnosis

A stack sample (`sample <pid>`) ruled out a deadlock immediately — the process was inside a normal
MLX generation loop:

```
mlx::core::async_eval(...)
  mlx::core::eval_impl(...)          960/993 samples
    std::condition_variable::wait    <- waiting on the GPU
  mlx::core::QuantizedMatmul::eval_gpu
    mlx::core::qmv(...)
```

It was generating, just pathologically slowly. The reason was memory:

```
python3.11 RSS            7,830 MB      <- on an 8 GB machine
vm.swapusage used         4,737 MB
system memory free        6%
```

Killing the process dropped swap from **4,737 MB to 2,054 MB** immediately, which confirmed the
process was the cause rather than a victim of unrelated system pressure.

### Root cause

MLX caches freed Metal buffers for reuse. In a long-lived evaluation process asking many questions
of **varying sequence length**, that cache grows monotonically — each new shape allocates rather
than reusing. Nothing in the pipeline ever released it. Per-question latency degraded from ~80 s
early in the run to **over 17 minutes** by question 25, as the machine moved from RAM to swap.

Training never hit this: `mlx_lm.lora` runs fixed-shape batches under a bounded seq length, so its
cache reaches a steady state. Peak memory there was flat at 4.6–4.7 GB for three hours. The
evaluation harness has the opposite shape — every question is a different length — which is
exactly the workload that defeats a size-keyed buffer cache.

### Fix

`src/qa/llm.py` gains `free_gpu_cache()` (`mx.clear_cache()`) and `cache_limit_gb()`
(`mx.set_cache_limit`). The harness calls the former **between questions** and caps the cache at
1 GB on load. Each result row now also records `rss_gb`, so if this ever regrows it shows up as
data rather than as an unexplained latency blow-out.

### What it cost, stated plainly

The first 24 arm-1 results had **contaminated latency measurements** — accuracy is unaffected
(slowness does not change a greedy-decoded output), but the timing numbers were meaningless. That
arm was re-run from scratch rather than resumed, so no contaminated timing survives into the
reported results.

### Relation to the earlier Metal OOMs

Stage 1 hit `kIOGPUCommandBufferCallbackErrorOutOfMemory` twice, both times because **I** ran
embedding work concurrently with a benchmark holding the 7B model. That was an operator error and
the lesson was "one model on the GPU at a time" — a rule this run followed. This failure is
different and was not covered by that rule: a **single** process, obeying it perfectly, still
exhausted memory through unbounded cache growth over time. The earlier lesson was necessary but
not sufficient, and I had assumed it was sufficient.

---

## Failure 4 — the entire arm-1 evaluation ran on the wrong model

The most consequential failure in Stage 2, and the one that would have been easiest to publish
without noticing.

### Symptom

Arm 2 (fine-tuned) completed all 35 questions in under five minutes — arm 1 had taken ~115 s per
question — and scored 0/35. Every row carried the same error:

```
ValueError: [matmul] Last dimension of first input with shape (1,1405,3584)
must match second to last dimension of second input with shape (2048,8).
```

`3584` is Qwen2.5-**7B**'s hidden size. `2048` is the **3B**'s, and the LoRA adapter is 3B-shaped.
The pipeline was running the 7B.

### Root cause — a Python default-argument binding bug I wrote

```python
MODEL_ID = "mlx-community/Qwen2.5-7B-Instruct-4bit"

def generate_text(prompt, max_tokens=512, system=None, model_id: str = MODEL_ID):
    model, tokenizer = get_llm(model_id)
```

A default argument is evaluated **once, at function-definition time**. The 2C harness sets
`llm_mod.MODEL_ID = BASE_3B` before running an arm, but `generate_text`'s default had already been
bound to the 7B at import. Reassigning the module global changed nothing.

### What it cost

**Arm 1's completed 35-question result — 4/35, 0/26 cross-document — was the 7B's score, not the
3B's.** I had already reported that number, along with a breakdown by operation and a paragraph
about what it implied. It was measuring a model that is not in the experiment. Discarded and re-run.

### Why it surfaced at all

Only because the fine-tuned arm existed. A LoRA adapter has a fixed shape, so applying a 3B adapter
to 7B weights throws immediately and loudly. **Without arm 2, arm 1 and arm 3 would both have run
on the 7B, produced entirely plausible numbers, and the comparison would have been published as a
3B before/after.** Nothing in the output would have looked wrong — the answers were well-formed,
latency was in a believable range, and the accuracy pattern (0/26 cross-doc, 4/9 controls) told a
coherent story that matched the Stage 1 diagnosis perfectly.

That is the uncomfortable part: the wrong-model result was *more* convincing than a noisy correct
one would have been, because it confirmed what I expected.

### The keyed cache worked; it just was not reached

`get_llm` was deliberately given a `(model_id, adapter)` cache key in 2B specifically so that
switching arms could not silently reuse the previous model. That guard was correct and did its job
— it detected the mismatch. But it keyed on the model_id it was *handed*, and the caller was
handing it a stale constant. A guard downstream of the corrupted value cannot catch corruption of
that value.

### Fix

`model_id` now defaults to `None` and resolves to the current `MODEL_ID` **at call time**:

```python
def get_llm(model_id: str = None, adapter_path: str = None):
    model_id = model_id or MODEL_ID          # resolved at CALL time, never at def time
```

Verified by loading and checking a weight shape: `q_proj` scales `(2048, 32)` confirms the 3B.

### Stage 1 impact — checked, and there is none

`src/quant/bench.py` has the same `llm_mod.MODEL_ID = model_id` pattern, so its `--model` flag was
latently broken too. But no reported Stage 1 number came from it:

- **INT4** ran with `model_id=None`, where the def-time default *is* the intended 7B-4bit. Correct.
- **INT8** was measured by a standalone attempt script that loaded explicitly. The captured log
  shows `requires 7717 MB` — the 8-bit footprint, roughly double 4-bit's — so the INT8 weights were
  genuinely loaded. Correct.
- **FP16** was never run.

So nothing in `results/quant_table.md` needs retracting. `bench.py --model` was non-functional and
never produced a published figure; it is fixed by the same change.

### Lesson

Failures 1 and 2 were instruments measuring the wrong quantity. This one is worse: the instrument
measured a *different system* and reported confidently about it. The only reason it was caught is
that one arm of the experiment was physically incapable of running on the wrong model. Designing
comparisons so that a misconfiguration **cannot** produce a plausible result — rather than trusting
that it will look wrong — is the actual takeaway.
