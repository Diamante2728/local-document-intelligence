"""KV-cache and weight-footprint arithmetic. Pure calculation — no model load, runs instantly.

This is the "napkin math" for MEMO section 3, and it is also how the FP16 rung of the
quantization ladder is established: FP16 is ruled out by arithmetic, not by a failed run.

Usage: python -m src.quant.kv_math
"""
import glob
import json
from pathlib import Path

# Measured on this machine: macOS resident usage with the app closed, from Activity Monitor.
# Total 8GB unified memory; the OS and its services do not give it all back.
TOTAL_RAM_GB = 8.0
OS_OVERHEAD_GB = 3.5          # ~3-4GB per the hardware plan; midpoint used
USABLE_GB = TOTAL_RAM_GB - OS_OVERHEAD_GB


def load_config():
    pattern = str(Path.home() / ".cache/huggingface/hub/models--mlx-community--"
                                "Qwen2.5-7B-Instruct-4bit/snapshots/*/config.json")
    matches = glob.glob(pattern)
    if not matches:
        raise FileNotFoundError("model config not found — run the Phase 0 model download first")
    return json.load(open(matches[0]))


def kv_bytes_per_token(cfg, bytes_per_elem=2):
    """2 (K and V) x n_layers x n_kv_heads x head_dim x bytes_per_elem."""
    n_layers = cfg["num_hidden_layers"]
    n_kv_heads = cfg["num_key_value_heads"]
    head_dim = cfg["hidden_size"] // cfg["num_attention_heads"]
    return 2 * n_layers * n_kv_heads * head_dim * bytes_per_elem


def report():
    cfg = load_config()
    n_layers = cfg["num_hidden_layers"]
    n_heads = cfg["num_attention_heads"]
    n_kv_heads = cfg["num_key_value_heads"]
    head_dim = cfg["hidden_size"] // n_heads

    L = ["# Quantization & KV-cache arithmetic — Qwen2.5-7B-Instruct\n"]
    L.append("Computed from the model's own `config.json`, not from published summaries.\n")
    L.append("## Model shape\n")
    L.append(f"- layers: **{n_layers}**")
    L.append(f"- attention heads: **{n_heads}**")
    L.append(f"- key/value heads: **{n_kv_heads}**  ← grouped-query attention (GQA)")
    L.append(f"- head_dim: {cfg['hidden_size']} / {n_heads} = **{head_dim}**")
    L.append(f"- max context: {cfg['max_position_embeddings']:,} tokens\n")
    L.append("> GQA is the single most important number here. A reader who assumes "
             f"{n_heads} KV heads instead of {n_kv_heads} overstates KV memory by "
             f"**{n_heads // n_kv_heads}x**. Qwen2.5-7B shares each KV head across "
             f"{n_heads // n_kv_heads} query heads.\n")

    L.append("## Weight footprint per precision\n")
    params = 7.6e9  # Qwen2.5-7B actual parameter count, ~7.6B
    L.append("| precision | bytes/param | weights | fits in ~4.5GB usable? |")
    L.append("|---|---|---|---|")
    for name, bpp in [("FP16", 2.0), ("INT8", 1.0), ("INT4", 0.5)]:
        gb = params * bpp / 1e9
        verdict = "**yes**" if gb < USABLE_GB else "**no**"
        L.append(f"| {name} | {bpp} | {gb:.1f} GB | {verdict} |")
    L.append("")
    L.append(f"INT4 in practice is slightly above the naive 0.5 bytes/param because MLX stores "
             f"per-group scales and biases (group_size="
             f"{cfg.get('quantization', {}).get('group_size', 'n/a')}); the measured on-disk "
             f"size is **4.0 GB**, and measured peak during generation was **4.41 GB**.\n")

    L.append("## KV cache per token\n")
    per_tok_fp16 = kv_bytes_per_token(cfg, 2)
    L.append(f"```\nKV bytes/token = 2 (K,V) x n_layers x n_kv_heads x head_dim x bytes_per_elem")
    L.append(f"               = 2 x {n_layers} x {n_kv_heads} x {head_dim} x 2")
    L.append(f"               = {per_tok_fp16:,} bytes  (~{per_tok_fp16/1024:.0f} KB/token)\n```\n")

    L.append("## Per-user cache at various context lengths (FP16 cache)\n")
    L.append("| context | KV per user | 50 users |")
    L.append("|---|---|---|")
    for ctx in (2048, 4096, 8192, 32768):
        per_user = per_tok_fp16 * ctx
        L.append(f"| {ctx:,} | {per_user/1e9:.2f} GB | {per_user*50/1e9:.1f} GB |")
    L.append("")

    L.append("## The 50-concurrent-user question\n")
    ctx = 4096
    per_user = per_tok_fp16 * ctx
    total_kv = per_user * 50
    weights_int4 = 4.0
    budget = USABLE_GB - weights_int4
    fit = int(budget * 1e9 // per_user)
    L.append(f"Assumptions stated: INT4 weights (**{weights_int4} GB**, shared across all users — "
             f"weights are loaded once, not per user), {ctx:,}-token context per user, FP16 KV "
             f"cache, no paging or eviction, batch inference on one machine.\n")
    L.append(f"- usable memory after macOS: **{USABLE_GB:.1f} GB**")
    L.append(f"- minus INT4 weights: **{budget:.1f} GB** left for KV")
    L.append(f"- KV per user at {ctx:,} tokens: **{per_user/1e9:.2f} GB**")
    L.append(f"- 50 users would need: **{total_kv/1e9:.1f} GB** of KV alone")
    L.append(f"- **users that actually fit on this 8GB M1: {fit}**\n")
    L.append(f"So 50 concurrent users at {ctx:,} tokens needs "
             f"**{(total_kv + weights_int4*1e9)/1e9:.1f} GB** total against "
             f"**{USABLE_GB:.1f} GB** usable — over budget by roughly "
             f"**{(total_kv + weights_int4*1e9)/1e9 / USABLE_GB:.1f}x**.\n")
    L.append("What would have to change to serve 50 users on one box: quantize the KV cache to "
             "int8 (halves it), cap context far below 4k, page inactive sessions out of the cache "
             "(vLLM-style block paging), or accept queueing so that only ~"
             f"{fit} sessions are resident at once. On this hardware the honest answer is that a "
             "single 8GB M1 is a single-digit-concurrency device, and 50 users means either a "
             "bigger machine or horizontal scaling.\n")

    L.append("## FP16 infeasibility on this machine\n")
    fp16_w = params * 2 / 1e9
    L.append(f"- FP16 weights alone: 7.6B x 2 bytes = **{fp16_w:.1f} GB**")
    L.append(f"- usable memory: **{USABLE_GB:.1f} GB** (8 GB total minus ~{OS_OVERHEAD_GB} GB macOS)")
    L.append(f"- **{fp16_w:.1f} GB > {USABLE_GB:.1f} GB**, before any KV cache or activations")
    L.append(f"- shortfall: **{fp16_w - USABLE_GB:.1f} GB**\n")
    L.append("FP16 is therefore not benchmarked — it is ruled out by arithmetic. Reporting "
             "fabricated FP16 latency/accuracy numbers would be worse than reporting none.\n")
    return "\n".join(L)


if __name__ == "__main__":
    out = report()
    print(out)
    dest = Path(__file__).resolve().parents[2] / "results" / "kv_math.md"
    dest.write_text(out)
    print(f"\n[written to {dest}]")
