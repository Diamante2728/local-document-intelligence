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
