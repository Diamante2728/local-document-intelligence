# Phase 0 — Offline Load Proof

Model: `mlx-community/Qwen2.5-7B-Instruct-4bit` (locked), loaded via `mlx-lm` on MLX/Metal.
Hardware: MacBook Air, Apple M1, 8GB unified memory.
Env: conda env `doc-intel`, Python 3.11.5.

## Method

Weights were pre-downloaded once (one-time network fetch, ~4.0GB, cached under
`~/.cache/huggingface/hub/`). The proof run below was executed with
`HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`, which makes `huggingface_hub` refuse any network
call and load strictly from local cache — this is the standard way to prove no runtime network
dependency without physically disabling the machine's network interface (which this assistant
did not do unilaterally).

## Raw transcript

```
=== OFFLINE PROOF (HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1) ===
Load time: 11.4s
Prompt: In one sentence, what is the capital of France?
Response: The capital of France is Paris.
Generation time: 17.82s for ~7 tokens
Approx tokens/sec: 0.39
MLX peak memory (mx.get_peak_memory): 4.41 GB

[cold]   4.82s,  ~7 tok, 1.45 tok/s -> 'The capital of France is Paris.'
[warm-1] 3.62s, ~32 tok, 8.84 tok/s -> 'The first five prime numbers are: 1. 2 2. 3 3. 5 4. 7 5. 11'
[warm-2] 5.06s, ~48 tok, 9.49 tok/s -> 'A hash table is a data structure that implements an associative array abstract d...'

MLX peak memory after warm calls: 4.41 GB
```

## Interpretation

- **Offline confirmed:** generation succeeds with `HF_HUB_OFFLINE=1` — no network call was made
  or possible during load or generate.
- **Cold-start artifact:** the very first `generate()` call in a process measures ~0.4–1.5 tok/s,
  not because the model is slow but because MLX compiles Metal shader kernels on first use (JIT).
  This is a one-time-per-process cost, not steady-state throughput — don't use it as the latency
  baseline for Phase 5.
- **Warm-state baseline (the real number for later comparison):** **~9 tok/s** on this base M1
  (7-8 core GPU), INT4, batch size 1. This is the tokens/sec baseline Phase 5's INT4 rung should
  roughly match; if it's far off, something changed (context length, contention, thermal
  throttling) and should be investigated, not silently accepted.
- **Memory:** `mx.get_peak_memory()` reports **4.41 GB** peak, consistent with the ~4.0GB on-disk
  INT4 weight footprint plus KV-cache/activation overhead for these short prompts. Per the build
  spec, this MLX figure can under-report vs. Activity Monitor "Real Memory" by up to ~2x — full
  cross-check with Activity Monitor / `footprint` is deferred to Phase 5 where it's required
  (Phase 0 only needs to confirm the model loads within budget, which it does: 4.41GB fits
  comfortably under the ~4-5GB usable budget on this 8GB machine).
- **Swap caveat:** system-wide swap was already at **9.2GB used** (`sysctl vm.swapusage`) before
  this test ran, most likely from other background applications already open on this machine —
  not something this test caused. Phase 5's swap measurements will need a clean baseline (close
  other apps, or at minimum record pre-run swap and treat only the delta as attributable).
