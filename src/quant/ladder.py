"""The three rungs of the quantization ladder, and how each is established.

    INT4  — measured in full (20 gold questions): accuracy by type, P50/P95, peak memory.
    INT8  — LOAD ATTEMPTED for real on this 8GB machine; whatever happens is the result.
    FP16  — not attempted. Ruled out by arithmetic (see src/quant/kv_math.py).

# DECISION: how the INT8 artifact is obtained
# The spec asks for one base model converted to three artifacts with a common q_group_size.
# We use `mlx-community/Qwen2.5-7B-Instruct-8bit` rather than downloading the ~15GB FP16 base
# and running `mlx_lm.convert` locally. Verified before choosing: that repo reports
# `quantization = {group_size: 64, bits: 8}` against the 4-bit's `{group_size: 64, bits: 4}` —
# same base model, same group size, same layer/KV-head geometry, differing only in bit width.
# So it is genuinely "the same model at two precisions", which is what the constraint is for.
#
# Why not convert locally: this machine has ~30GB free. The FP16 route needs ~15GB of download
# plus ~8GB of output, leaving ~7GB on a disk whose OS is already swapping several GB. The
# measurement would be taken under disk pressure that we introduced. The deviation is recorded
# here rather than hidden, because "I converted these myself" would be a false claim.
#
# Why FP16 is not downloaded at all: it cannot run (15.2GB weights vs ~4.5GB usable), so the
# only thing a download would buy is the ability to say we tried. The arithmetic is the honest
# evidence; fabricating or padding an FP16 row would be worse than an empty one.

INT8_REPO = "mlx-community/Qwen2.5-7B-Instruct-8bit"
INT4_REPO = "mlx-community/Qwen2.5-7B-Instruct-4bit"
"""
import argparse
import json
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INT8_REPO = "mlx-community/Qwen2.5-7B-Instruct-8bit"
INT4_REPO = "mlx-community/Qwen2.5-7B-Instruct-4bit"


def fetch(repo):
    """Download an artifact. Needs network; this is setup, not runtime."""
    import os
    os.environ.pop("HF_HUB_OFFLINE", None)
    from huggingface_hub import snapshot_download
    print(f"fetching {repo} ...")
    t0 = time.perf_counter()
    path = snapshot_download(repo)
    print(f"  -> {path}  ({time.perf_counter()-t0:.0f}s)")
    return path


def attempt_load(repo, generate_tokens=48):
    """Try to load and generate. Records exactly what happens, including failure.

    An OOM, a swap storm or a kill is a RESULT, not an error to be handled away — on an 8GB
    machine that wall is the most interesting finding the ladder can produce.
    """
    from .measure import MemoryProbe, swap_used_mb

    record = {"repo": repo, "loaded": False, "generated": False,
              "swap_before_mb": swap_used_mb(), "error": None}
    print(f"\n=== attempting {repo} ===")
    print(f"swap before: {record['swap_before_mb']} MB")

    try:
        with MemoryProbe() as probe:
            from mlx_lm import load, generate
            t0 = time.perf_counter()
            model, tokenizer = load(repo)
            record["load_s"] = round(time.perf_counter() - t0, 1)
            record["loaded"] = True
            print(f"  loaded in {record['load_s']}s")

            messages = [{"role": "user", "content": "In one sentence, what is a hash table?"}]
            formatted = tokenizer.apply_chat_template(messages, add_generation_prompt=True)
            t0 = time.perf_counter()
            text = generate(model, tokenizer, prompt=formatted,
                            max_tokens=generate_tokens, verbose=False)
            dt = time.perf_counter() - t0
            n_tok = len(tokenizer.encode(text))
            record["generated"] = True
            record["gen_s"] = round(dt, 2)
            record["tokens"] = n_tok
            record["tok_per_s"] = round(n_tok / dt, 2) if dt else None
            record["sample"] = text.strip()[:120]
            print(f"  generated {n_tok} tok in {dt:.1f}s ({record['tok_per_s']} tok/s)")
        record["memory"] = probe.as_dict()
    except Exception as e:
        record["error"] = f"{type(e).__name__}: {e}"
        record["memory"] = probe.as_dict() if "probe" in dir() else None
        print(f"  FAILED: {record['error']}")

    record["swap_after_mb"] = swap_used_mb()
    if record["swap_before_mb"] is not None and record["swap_after_mb"] is not None:
        record["swap_delta_mb"] = round(record["swap_after_mb"] - record["swap_before_mb"], 1)
        print(f"swap after: {record['swap_after_mb']} MB  (delta {record['swap_delta_mb']:+.1f} MB)")
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["fetch-int8", "try-int8", "try-int4"])
    args = ap.parse_args()

    if args.action == "fetch-int8":
        fetch(INT8_REPO)
        return

    repo = INT8_REPO if args.action == "try-int8" else INT4_REPO
    rec = attempt_load(repo)
    out = REPO_ROOT / "results" / f"loadtest_{args.action.replace('try-', '')}.json"
    out.write_text(json.dumps(rec, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
