# Quantization Ladder — Deliverable 1D

Apple M1, 8 GB unified memory. Qwen2.5-7B-Instruct, `group_size=64` held constant across rungs
(verified: the 4-bit and 8-bit artifacts both report `{group_size: 64}` with identical
28 layers / 4 KV heads, so this is the same model at different precisions).

---

## Tradeoff table

| rung | prose | numeric | multi-doc | overall | P50 | P95 | MLX peak | OS footprint | status |
|---|---|---|---|---|---|---|---|---|---|
| **FP16** | — | — | — | — | — | — | — | — | **not run — arithmetic, see §1** |
| **INT8** | — | — | — | — | — | — | 8.12 GB | 8.00 GB | **loads, cannot generate — Metal OOM, see §2** |
| **INT4** | 6/8 | 4/8 | 1/4 | **11/20 = 0.55** | 99.7 s | 244.0 s | 5.91 GB | 6.64 GB | **measured working rung, see §3** |

INT4 held-out (9 fresh questions, 7 documents never inspected): **8/9 = 0.889**, P50 29.3 s,
MLX peak 5.11 GB. See §4 for why held-out and gold-set numbers differ.

**No INT8 or FP16 accuracy figures appear anywhere in this document.** Neither rung produced a
single token, so any per-type accuracy number for them would be fabricated. "Not run, here is the
mechanism" is the finding.

---

## §1 — The memory budget, stated once

Everything below is measured against this budget.

| quantity | value | source |
|---|---|---|
| total unified memory | 8.00 GB | hardware |
| macOS + services resident | ~3.5 GB | Activity Monitor, idle |
| **usable for our process (our estimate)** | **~4.5 GB** | 8.0 − 3.5 |
| **MLX's own recommended maximum** | **5.46 GB** | emitted by mlx-lm at runtime (see §2) |

The second figure is the more authoritative one and we did not have to guess it — `mlx-lm`
printed it during the INT8 attempt. We report both; they agree to within ~1 GB and tell the same
story.

**KV cache, from the model's real config** (not estimated):

```
n_layers = 28,  n_kv_heads = 4 (GQA),  head_dim = 3584/28 = 128

KV bytes/token = 2 (K,V) × n_layers × n_kv_heads × head_dim × 2 bytes
               = 2 × 28 × 4 × 128 × 2
               = 57,344 bytes = 56 KB/token

at 4,096-token context = 0.23 GB per concurrent request
```

Note GQA: 4 KV heads, not 28. Assuming multi-head attention would overstate KV memory by **7×**.

---

## §2 — FP16 and INT8: the arithmetic, and what actually happened

### Per-rung footprint vs budget

| rung | weights | + KV @ 4k | **total needed** | usable (~4.5 GB) | **gap** | MLX max (5.46 GB) | **gap** |
|---|---|---|---|---|---|---|---|
| FP16 | 7.6B × 2 B = **15.20 GB** | 0.23 GB | **15.43 GB** | 4.5 GB | **−10.93 GB** | 5.46 GB | **−9.97 GB** |
| INT8 | 7.6B × 1 B = **7.60 GB** | 0.23 GB | **7.83 GB** | 4.5 GB | **−3.33 GB** | 5.46 GB | **−2.37 GB** |
| INT4 | 7.6B × 0.5 B = **3.80 GB** | 0.23 GB | **4.03 GB** | 4.5 GB | **+0.47 GB** | 5.46 GB | **+1.43 GB** |

INT4 is the only rung with a positive margin, and even that margin is thin — measured peak during
multi-doc questions reached **5.91 GB**, i.e. it exceeds the 4.5 GB estimate and eats most of the
5.46 GB MLX headroom once activations and a real prompt are included.

### FP16 — not attempted, and that is deliberate

15.43 GB needed against 8.00 GB of physical memory. The shortfall (**10.93 GB**) is larger than
the entire machine. No configuration change — smaller context, smaller batch, KV quantization —
closes a gap of that size, because the *weights alone* are 15.20 GB before a single token of
cache. Downloading a 15 GB artifact to watch it fail would produce no information the arithmetic
does not already give.

### INT8 — attempted for real, and it failed in an informative way

Run 2026-08-12, clean start (swap at 1,008 MB before launch).

```
=== attempting mlx-community/Qwen2.5-7B-Instruct-8bit ===
swap before: 1007.62 MB
  loaded in 10.2s
[WARNING] Generating with a model that requires 7717 MB which is close to the
          maximum recommended size of 5461 MB. This can be slow.
  FAILED: RuntimeError: [METAL] Command buffer execution failed:
          Insufficient Memory (00000008:kIOGPUCommandBufferCallbackErrorOutOfMemory).
swap after: 3951.81 MB  (delta +2944.2 MB)
```

**The failure mode is "loads, then dies on generation" — not a hard OOM at load.** That
distinction matters:

- **Weights loaded successfully in 10.2 s.** MLX mapped 7.6 GB of weights without erroring,
  because macOS backed the allocation with swap rather than refusing it.
- **`mlx-lm` itself flagged the problem** before failing, and quantified it: **7,717 MB required
  vs 5,461 MB recommended maximum** — a **1.41× overrun**.
- **Generation then failed at the Metal layer**, not the Python layer:
  `kIOGPUCommandBufferCallbackErrorOutOfMemory`. The GPU command buffer could not obtain memory
  for the forward pass. Weights being resident is not sufficient; activations and KV cache need
  headroom on top, and there was none.
- **Swap grew by 2,944 MB** during the attempt, peaking at 5,767 MB mid-load (sampled at 10 s
  intervals). The machine was actively thrashing at the point of failure.

Measured at failure: **MLX peak 8.12 GB, OS footprint 8.00 GB** — i.e. the process was holding
essentially the entire physical memory of the machine when the GPU allocator gave up.

**Mechanism in one sentence:** on unified memory, INT8 weights fit *only* because macOS pages them
to swap, and the Metal command buffer then cannot allocate the additional working memory a forward
pass requires — so the model is loadable but not runnable, which is a stricter failure than simply
"too big".

**Corroborating evidence** that this is a real ceiling and not a one-off: a Metal OOM with the
identical error code was independently observed twice during this build when the **INT4** model
was resident and a 130 MB embedding model was asked to run on the GPU concurrently. If INT4 plus
130 MB can exhaust the allocator, INT8 at 7.6 GB has no path.

Raw record: `results/loadtest_int8.json`.

---

## §3 — INT4: the working rung, measured

**Gold set (development set, 20 questions):**

| type | accuracy | citation |
|---|---|---|
| prose | 6/8 = 0.75 | 8/8 |
| numeric | 4/8 = 0.50 | 8/8 |
| multi-doc | 1/4 = 0.25 | 2/4 |
| **overall** | **11/20 = 0.55** | 0.90 |

- latency **P50 99.7 s**, **P95 244.0 s**, mean 122.5 s, wall clock 46 min
- memory **MLX peak 5.91 GB**, **OS footprint 6.64 GB** (MLX under-reports by 0.73 GB)
- swap: max single-question delta 386 MB

**Where the damage concentrates:** numeric (0.50) sits below prose (0.75), which matches the
prediction in the build spec that cell-lookup precision degrades first. The failures are
overwhelmingly *column selection* — the system returns a real cell from the correct row but the
wrong column (N04 baseline returned 0.46 against 498.5; N05 returned 0.54 against 0.91).

**This cannot be attributed to INT4.** With one runnable rung there is no comparison point. What
we can say is that these are *system* characteristics at INT4, not *precision-induced* ones. Any
claim that "INT4 degrades numeric accuracy" would require an INT8 baseline we were unable to
obtain, for the reasons in §2.

---

## §4 — Held-out results and the composition caveat

| set | overall | prose | numeric | multi-doc | P50 |
|---|---|---|---|---|---|
| gold set (tuned against) | 11/20 = 0.55 | 6/8 | 4/8 | 1/4 | 99.7 s |
| held-out (never inspected) | **8/9 = 0.889** | **8/8** | **0 questions** | 0/1 | 29.3 s |

**The held-out set contains ZERO numeric questions.** Its composition is 8 prose + 1 multi-doc.
This is the primary explanation for the 0.55 → 0.889 gap and it must be stated before any other:
the held-out set omits the question type on which the system scores worst (numeric, 0.50). It is
not evidence of better general capability, and it is not a like-for-like comparison.

A secondary, weaker explanation also holds: the gold set's numeric block is 100% FDIC
multi-section tables, the corpus's hardest extraction target. But the composition difference is
the simpler and larger effect, and should lead.

What the held-out result *does* legitimately support: **8/8 observed on held-out prose, consistent
with the gold-set prose rate (6/8), with no evidence of degradation on unseen documents.** With
n=8 this is not a stable 100% accuracy claim and should not be reported as one.

---

## §5 — Caveats on every number above

1. **P95 measures swap, not model speed.** One question was observed at 494 s against a ~90 s
   median, and `ps` itself failed with *sysmond service not found* mid-run. Treat P50 as the
   model characteristic, P95 as a memory-pressure characteristic.
2. **`ps` RSS is unusable on Metal** — ~50 MB reported against ~5.6 GB `footprint` for the same
   loaded model, because unified-memory buffers are not counted in RSS. All figures above use
   `footprint`. The measured MLX-vs-OS gap was **0.31–0.87 GB**, not the ~2× the build spec
   anticipated.
3. **The INT8 artifact is pre-quantized, not locally converted.** `group_size=64` and the layer
   geometry match the 4-bit exactly, so it is the same model at two precisions. Local conversion
   would have required ~23 GB against ~30 GB free on an already-swapping disk.
4. **Multi-doc (1/4, 0/1) drags the overall number down** and is a documented structural weakness
   — see `results/multidoc_failure_analysis.md`.
5. **Four improvement attempts produced net-zero score movement** (11/20 → 11/20) with a
   citation-rate regression (1.00 → 0.90). See `results/fix_attempt_analysis.md`.

---

## §6 — Deployment recommendation

**Ship INT4 on 8 GB Apple Silicon. It is not the best rung available; it is the only one that
runs.**

- FP16 is short by **10.93 GB** — larger than the machine. Not a tuning problem.
- INT8 is short by **2.37 GB** against MLX's own recommended maximum, and was *measured* to load
  and then fail at the Metal layer during generation, with swap growing 2.9 GB.
- INT4 clears the budget by **+1.43 GB** on paper, but measured peak reached 5.91 GB under
  multi-doc load — most of the available headroom.

Operational constraints that follow from the measurements, not from preference:

- **Do not co-locate other GPU work.** The 7B INT4 model plus a 130 MB embedding model was
  sufficient to fail the Metal allocator, twice.
- **Concurrency is single-digit.** KV cache is 56 KB/token; at 4k context, 50 users need
  **11.7 GB of cache alone** against ~4.5 GB usable — roughly **3.5× over budget** including
  weights. Two users fit. Fifty means a larger machine or horizontal scaling, not tuning.
- **Budget for P95, not P50.** Swap turns a ~90 s question into a ~500 s question without warning.
- **Cap context and `--max-kv-size`.** KV is the term that scales with users and it exhausts
  memory before anything else does.

If INT8 quality is required, the answer is a 16 GB machine. On this hardware it is not a
configuration choice — it is unavailable.
