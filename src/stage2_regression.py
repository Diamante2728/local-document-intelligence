"""Stage 2C(ii) — regression suite: did the adapter damage anything else?

    python -m src.stage2_regression --suite arc    --arm base|tuned
    python -m src.stage2_regression --suite stage1 --arm base|tuned

A LoRA that fixes multi-doc by destroying general ability or Stage 1's prose/numeric behaviour is
not an improvement. Two independent slices:

  arc     ARC-Easy + ARC-Challenge, read from the local HF parquet cache. General multiple-choice
          reasoning, entirely unrelated to this corpus. Detects broad capability damage.
  stage1  The prose and numeric questions from gold_set.json, through the real pipeline. Detects
          damage to the behaviour Stage 1 actually shipped — including the abstention behaviour
          the training set's 24% negatives were designed to preserve.

Both run offline from cache. Degradation is reported as measured; a fine-tune that trades general
ability for a narrow win is a finding, not something to bury.
"""
import argparse
import glob
import json
import random
import re
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_3B = "mlx-community/Qwen2.5-3B-Instruct-4bit"
ADAPTER = str(REPO_ROOT / "results" / "adapters" / "multidoc_r8")
ARC_GLOB = ("/Users/mangilipallinagaraj/.cache/huggingface/hub/datasets--allenai--ai2_arc/"
            "**/*.parquet")

ARC_SYSTEM = ("Answer the multiple-choice question. Reply with ONLY the letter of the correct "
              "choice (A, B, C, D, or E). No explanation.")


def configure(arm):
    from .qa import llm as llm_mod
    adapter = ADAPTER if arm == "tuned" else None
    llm_mod.MODEL_ID = BASE_3B
    llm_mod.ADAPTER_PATH = adapter
    llm_mod.cache_limit_gb(1.0)
    llm_mod.get_llm(BASE_3B, adapter)
    return adapter


def load_arc(n_per_split=60, seed=13):
    import pyarrow.parquet as pq
    rng = random.Random(seed)
    out = []
    for path in sorted(glob.glob(ARC_GLOB, recursive=True)):
        split = "ARC-Challenge" if "Challenge" in path else "ARC-Easy"
        t = pq.read_table(path).to_pylist()
        # Fixed seed and a fixed slice so base and tuned see IDENTICAL questions. Sampling
        # differently per arm would make the comparison meaningless.
        for r in rng.sample(t, min(n_per_split, len(t))):
            out.append({"split": split, "id": r["id"], "question": r["question"],
                        "labels": list(r["choices"]["label"]),
                        "texts": list(r["choices"]["text"]),
                        "answer": r["answerKey"]})
    return out


def run_arc(arm, n_per_split=60):
    from .qa.llm import generate_text
    configure(arm)
    items = load_arc(n_per_split)
    out_path = REPO_ROOT / "results" / f"regress_arc_{arm}.jsonl"
    done = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["id"])
    rows = [json.loads(l) for l in out_path.read_text().splitlines()] if out_path.exists() else []

    for i, it in enumerate(items, 1):
        if it["id"] in done:
            continue
        choices = "\n".join(f"{l}. {t}" for l, t in zip(it["labels"], it["texts"]))
        prompt = f"{it['question']}\n\n{choices}\n\nAnswer:"
        t0 = time.perf_counter()
        try:
            text, _ = generate_text(prompt, max_tokens=8, system=ARC_SYSTEM)
            err = None
        except Exception as e:
            text, err = "", f"{type(e).__name__}: {e}"
        m = re.search(r"\b([A-E1-5])\b", text.strip())
        pred = m.group(1) if m else ""
        row = {"id": it["id"], "split": it["split"], "arm": arm, "pred": pred,
               "gold": it["answer"], "correct": pred == it["answer"],
               "raw": text.strip()[:40], "latency_s": round(time.perf_counter() - t0, 2),
               "error": err}
        rows.append(row)
        with open(out_path, "a") as fh:
            fh.write(json.dumps(row) + "\n")
            fh.flush()
        if i % 10 == 0:
            from .qa.llm import free_gpu_cache
            free_gpu_cache()
        if i % 20 == 0:
            acc = sum(r["correct"] for r in rows) / len(rows)
            print(f"  [{i}/{len(items)}] running acc {acc:.3f}")
    acc = sum(r["correct"] for r in rows) / len(rows) if rows else 0
    by = {}
    for r in rows:
        b = by.setdefault(r["split"], [0, 0])
        b[0] += int(r["correct"])
        b[1] += 1
    print(f"[arc/{arm}] overall {acc:.3f} ({sum(r['correct'] for r in rows)}/{len(rows)})")
    for k, (c, n) in sorted(by.items()):
        print(f"    {k:<14} {c}/{n} = {c/n:.3f}")
    return rows


def run_stage1(arm):
    """Stage 1's prose and numeric gold questions through the real pipeline."""
    from .qa import answer as answer_mod
    from .quant.bench import grade
    configure(arm)
    # Arms 1/2 differ only by adapter; the arm-3 pipeline flags must be off here.
    answer_mod.MULTIDOC_DECOMPOSE = False
    answer_mod.PROSE_FEWSHOT = False

    gold = json.load(open(REPO_ROOT / "gold_set.json"))["questions"]
    qs = [q for q in gold if q["type"] in ("prose", "numeric")]
    out_path = REPO_ROOT / "results" / f"regress_stage1_{arm}.jsonl"
    done = {}
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                done[r["id"]] = r

    rows = []
    for i, q in enumerate(qs, 1):
        if q["id"] in done:
            rows.append(done[q["id"]])
            continue
        t0 = time.perf_counter()
        try:
            res = answer_mod.answer(q["question"], use_llm_router=False)
            err = None
        except Exception as e:
            res, err = {"answer": "", "citations": []}, f"{type(e).__name__}: {e}"
        ok, why = (False, err) if err else grade(q, res)
        row = {"id": q["id"], "type": q["type"], "arm": arm, "correct": bool(ok), "why": why,
               "answer": str(res.get("answer", ""))[:220], "path": res.get("path_taken"),
               "confidence": res.get("confidence"),
               "latency_s": round(time.perf_counter() - t0, 2), "error": err}
        rows.append(row)
        with open(out_path, "a") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
            fh.flush()
        from .qa.llm import free_gpu_cache
        free_gpu_cache()
        print(f"  [{i}/{len(qs)}] {q['id']:<4} {q['type']:<8} "
              f"{'OK ' if ok else 'MISS'} {row['latency_s']:6.1f}s  {why[:56]}")
    acc = sum(r["correct"] for r in rows) / len(rows) if rows else 0
    print(f"[stage1/{arm}] {sum(r['correct'] for r in rows)}/{len(rows)} = {acc:.3f}")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", choices=["arc", "stage1"], required=True)
    ap.add_argument("--arm", choices=["base", "tuned"], required=True)
    ap.add_argument("--n", type=int, default=60, help="ARC questions per split")
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()

    if args.fresh:
        (REPO_ROOT / "results" / f"regress_{args.suite}_{args.arm}.jsonl").unlink(missing_ok=True)
    if args.suite == "arc":
        run_arc(args.arm, args.n)
    else:
        run_stage1(args.arm)


if __name__ == "__main__":
    main()
