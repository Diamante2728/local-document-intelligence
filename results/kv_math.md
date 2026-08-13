# Quantization & KV-cache arithmetic — Qwen2.5-7B-Instruct

Computed from the model's own `config.json`, not from published summaries.

## Model shape

- layers: **28**
- attention heads: **28**
- key/value heads: **4**  ← grouped-query attention (GQA)
- head_dim: 3584 / 28 = **128**
- max context: 32,768 tokens

> GQA is the single most important number here. A reader who assumes 28 KV heads instead of 4 overstates KV memory by **7x**. Qwen2.5-7B shares each KV head across 7 query heads.

## Weight footprint per precision

| precision | bytes/param | weights | fits in ~4.5GB usable? |
|---|---|---|---|
| FP16 | 2.0 | 15.2 GB | **no** |
| INT8 | 1.0 | 7.6 GB | **no** |
| INT4 | 0.5 | 3.8 GB | **yes** |

INT4 in practice is slightly above the naive 0.5 bytes/param because MLX stores per-group scales and biases (group_size=64); the measured on-disk size is **4.0 GB**, and measured peak during generation was **4.41 GB**.

## KV cache per token

```
KV bytes/token = 2 (K,V) x n_layers x n_kv_heads x head_dim x bytes_per_elem
               = 2 x 28 x 4 x 128 x 2
               = 57,344 bytes  (~56 KB/token)
```

## Per-user cache at various context lengths (FP16 cache)

| context | KV per user | 50 users |
|---|---|---|
| 2,048 | 0.12 GB | 5.9 GB |
| 4,096 | 0.23 GB | 11.7 GB |
| 8,192 | 0.47 GB | 23.5 GB |
| 32,768 | 1.88 GB | 94.0 GB |

## The 50-concurrent-user question

Assumptions stated: INT4 weights (**4.0 GB**, shared across all users — weights are loaded once, not per user), 4,096-token context per user, FP16 KV cache, no paging or eviction, batch inference on one machine.

- usable memory after macOS: **4.5 GB**
- minus INT4 weights: **0.5 GB** left for KV
- KV per user at 4,096 tokens: **0.23 GB**
- 50 users would need: **11.7 GB** of KV alone
- **users that actually fit on this 8GB M1: 2**

So 50 concurrent users at 4,096 tokens needs **15.7 GB** total against **4.5 GB** usable — over budget by roughly **3.5x**.

What would have to change to serve 50 users on one box: quantize the KV cache to int8 (halves it), cap context far below 4k, page inactive sessions out of the cache (vLLM-style block paging), or accept queueing so that only ~2 sessions are resident at once. On this hardware the honest answer is that a single 8GB M1 is a single-digit-concurrency device, and 50 users means either a bigger machine or horizontal scaling.

## FP16 infeasibility on this machine

- FP16 weights alone: 7.6B x 2 bytes = **15.2 GB**
- usable memory: **4.5 GB** (8 GB total minus ~3.5 GB macOS)
- **15.2 GB > 4.5 GB**, before any KV cache or activations
- shortfall: **10.7 GB**

FP16 is therefore not benchmarked — it is ruled out by arithmetic. Reporting fabricated FP16 latency/accuracy numbers would be worse than reporting none.
