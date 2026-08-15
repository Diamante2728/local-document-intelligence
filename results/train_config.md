# 2B hyperparameters and why

Base: `mlx-community/Qwen2.5-3B-Instruct-4bit` (3.09B params, 4-bit). Trainable 6.65M = 0.216%.

| setting | value | reasoning |
|---|---|---|
| `fine-tune-type` | lora | QLoRA on an already-4-bit base; full FT of 3B needs optimizer state far beyond 8 GB |
| rank | 8 | Task is a **behavioural** change (answer the supported half instead of declining), not new knowledge. Rank 8 = 0.216% trainable, enough for a response-format shift; higher rank raises overfitting risk on 621 examples |
| `num-layers` | 16 of 36 | Top-16 only. Memory-bound at 8 GB; behaviour/format changes are concentrated in later layers, while early layers carry general representation we do not want to disturb |
| `batch-size` | 1 | 8 GB unified memory with sequences up to 2048 tokens |
| `grad-accumulation-steps` | 4 | Effective batch 4. Batch 1 alone gives very noisy gradients; accumulation buys stability without the memory of a real batch. Lowered from 8 to 4 to double the number of optimizer updates for the same wall clock — see failure 2 |
| `max-seq-length` | 2048 | **Not the 512 the brief suggested** — 91.9% of examples exceed 512 tokens, and mlx_lm truncates from the END, which is where the assistant target lives. Training at 512 would train most examples on a cut-off target |
| `--mask-prompt` | on | Loss on assistant tokens only. Without it the model is trained to reproduce the excerpts rather than the answering behaviour |
| `--grad-checkpoint` | on | Recompute activations; required to stay under the 5.73 GB Metal working set at 2048 tokens |
| `learning-rate` | 1e-4 | mlx_lm's 1e-5 default is tuned for much larger datasets; with 621 examples and ~78 optimizer steps/epoch, 1e-5 would barely move the adapter. 1e-4 is the standard LoRA band |
| `iters` | 800 | **`--iters` counts BATCHES, not optimizer steps** — see `results/training_issues.md` failure 2, where I first set 240 believing it was ~3 epochs when it was 0.39 epochs and 30 weight updates. With `batch_size=1`: 800 sequences = **1.29 epochs**, and 800/4 = **200 optimizer updates**. Three full epochs would be 1,863 iters ≈ 5.4 h; rejected on wall clock, recorded as a tradeoff |
| `seed` | 42 | reproducibility |

Data: 621 train / 68 valid, all verified to fit 2048 tokens **including** the assistant target.

## Corrections made to this config after it was first written

Both came from `results/training_issues.md` and are listed here so the table above is not read as
if it were right the first time:

1. `max_seq_length` — data was rebuilt after 9 examples were found whose prompt alone exceeded the
   budget, which produced NaN loss under `--mask-prompt`.
2. `iters` / `grad-accumulation-steps` — the original 240/8 was based on a wrong reading of what
   `--iters` counts, and would have trained for 0.39 epochs with 30 weight updates.
