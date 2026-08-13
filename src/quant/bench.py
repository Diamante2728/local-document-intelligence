"""Run the gold set against a model and record accuracy-by-type, latency and memory.

Designed so you never have to run the whole ladder to check that it works:

    python -m src.quant.bench --limit 2          # ~2 min, proves the harness end to end
    python -m src.quant.bench --type numeric     # just the numeric questions
    python -m src.quant.bench                    # full 20-question INT4 baseline

Routing is forced to rules-only (`--no-llm-router` equivalent). This is deliberate: if routing
were LLM-driven, an INT4-vs-INT8 accuracy difference would partly reflect routing noise rather
than answer quality, and the ladder exists to isolate the effect of precision.
"""
import argparse
import json
import re
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _norm_num(x):
    try:
        return float(str(x).replace(",", "").replace("$", "").rstrip("%"))
    except (TypeError, ValueError):
        return None


def grade(q, result):
    """Returns (correct: bool, why: str). Grading rules differ by question type."""
    ans = result.get("answer", "")

    if q["type"] == "numeric":
        got = result.get("value")
        if got is None:
            got = _norm_num(re.sub(r"[^\d.\-]", "", ans.split()[0]) if ans.split() else "")
        want = float(q["expected_answer"])
        if got is None:
            return False, f"no numeric value produced (answer={ans[:60]!r})"
        # 0.5% relative tolerance: published tables round, 0.60 vs 0.6 is the same fact.
        denom = max(abs(want), 1e-9)
        ok = abs(got - want) / denom <= 0.005
        return ok, f"got {got} want {want}"

    # prose / multi-doc: every required token must appear in the answer text.
    needles = q.get("answer_contains", [])
    if not needles:
        return False, "no answer_contains specified"
    missing = [n for n in needles if n not in ans]
    return (not missing), ("all key figures present" if not missing
                           else f"missing {missing} in {ans[:70]!r}")


def cited_docs(result):
    out = set()
    for c in result.get("citations", []) or []:
        if isinstance(c, dict) and c.get("doc"):
            out.add(c["doc"])
    return out


def citation_ok(q, result):
    """Did the answer cite the document(s) the gold set expects?"""
    exp = q.get("expected_citation")
    got = cited_docs(result)
    if not got:
        return False
    if isinstance(exp, list):
        want = {e["doc"] for e in exp}
        return len(want & got) >= 1   # multi-doc: credit partial source overlap
    return exp["doc"] in got


def _partial_path(label):
    return REPO_ROOT / "results" / f"bench_{label}.partial.jsonl"


def _load_partial(label):
    """Rows already completed by an earlier (possibly interrupted) run of the same label."""
    path = _partial_path(label)
    if not path.exists():
        return {}
    done = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # a torn final line from a hard kill — drop just that one
        done[row["id"]] = row
    return done


def run_bench(limit=None, qtype=None, label="int4", model_id=None, resume=False,
              fresh=False, holdout=False):
    from ..qa import answer as answer_mod
    from .measure import MemoryProbe, percentile, swap_used_mb

    if model_id:
        # Point the shared LLM wrapper at a different artifact for this run.
        from ..qa import llm as llm_mod
        llm_mod.MODEL_ID = model_id
        llm_mod._model = None
        llm_mod._tokenizer = None

    qfile = "holdout_set.json" if holdout else "gold_set.json"
    gold = json.load(open(REPO_ROOT / qfile))["questions"]
    if qtype:
        gold = [q for q in gold if q["type"] == qtype]
    if limit:
        gold = gold[:limit]

    # Checkpointing. A full run takes ~40 min on this machine and an earlier one lost 19 of 20
    # completed questions to a session teardown because results were only written at the end.
    partial = _partial_path(label)
    if fresh and partial.exists():
        partial.unlink()
    done = _load_partial(label) if resume else {}
    if done:
        print(f"[{label}] resuming: {len(done)} question(s) already complete "
              f"({', '.join(sorted(done))})")
    partial.parent.mkdir(parents=True, exist_ok=True)

    print(f"[{label}] {len(gold)} questions, model={model_id or 'default INT4'}")
    print(f"[{label}] swap before run: {swap_used_mb()} MB")

    rows, latencies = [], []
    t_start = time.perf_counter()
    for i, q in enumerate(gold, 1):
        if q["id"] in done:
            row = done[q["id"]]
            rows.append(row)
            latencies.append(row["latency_s"])
            print(f"  [{i}/{len(gold)}] {q['id']} {q['type']:<9} SKIP (already done)")
            continue
        with MemoryProbe() as probe:
            try:
                result = answer_mod.answer(q["question"], use_llm_router=False)
                err = None
            except Exception as e:                      # a rung that cannot run is a result
                result, err = {"answer": "", "citations": []}, f"{type(e).__name__}: {e}"
        ok, why = (False, err) if err else grade(q, result)
        cit = False if err else citation_ok(q, result)
        latencies.append(probe.elapsed_s)
        row = {
            "id": q["id"], "type": q["type"], "correct": ok, "citation_ok": cit,
            "why": why, "latency_s": round(probe.elapsed_s, 2),
            "confidence": result.get("confidence"), "path": result.get("path_taken"),
            "memory": probe.as_dict(), "error": err,
        }
        rows.append(row)
        # Flush immediately: everything above this line is lost if the process dies.
        with open(partial, "a") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
            fh.flush()
        print(f"  [{i}/{len(gold)}] {q['id']} {q['type']:<9} "
              f"{'OK ' if ok else 'MISS'} {probe.elapsed_s:6.1f}s  cite={'y' if cit else 'n'}  {why[:52]}")

    total = time.perf_counter() - t_start
    by_type = {}
    for r in rows:
        b = by_type.setdefault(r["type"], {"n": 0, "correct": 0, "cited": 0})
        b["n"] += 1
        b["correct"] += int(r["correct"])
        b["cited"] += int(r["citation_ok"])

    peaks = [r["memory"]["mlx_peak_gb"] for r in rows if r["memory"]["mlx_peak_gb"]]
    # footprint, not ps RSS: Metal unified-memory buffers do not appear in RSS (measured ~50 MB
    # RSS against 5.6 GB footprint for the same loaded model), so RSS would understate by ~100x.
    rss = [r["memory"]["os_footprint_gb"] for r in rows if r["memory"].get("os_footprint_gb")]
    swap_deltas = [r["memory"]["swap_delta_mb"] for r in rows
                   if r["memory"].get("swap_delta_mb") is not None]
    summary = {
        "label": label, "model_id": model_id, "n": len(rows),
        "accuracy_overall": round(sum(r["correct"] for r in rows) / len(rows), 3) if rows else 0,
        "citation_rate": round(sum(r["citation_ok"] for r in rows) / len(rows), 3) if rows else 0,
        "by_type": {k: {**v, "accuracy": round(v["correct"] / v["n"], 3)} for k, v in by_type.items()},
        "latency_p50_s": round(percentile(latencies, 50), 2) if latencies else None,
        "latency_p95_s": round(percentile(latencies, 95), 2) if latencies else None,
        "latency_mean_s": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "wall_clock_s": round(total, 1),
        "mlx_peak_gb_max": round(max(peaks), 3) if peaks else None,
        "os_footprint_gb_max": round(max(rss), 3) if rss else None,
        "mlx_vs_os_gap_gb": (round(max(rss) - max(peaks), 3)
                             if rss and peaks else None),
        "swap_after_mb": swap_used_mb(),
        "swap_max_delta_mb": round(max(swap_deltas), 1) if swap_deltas else None,
    }
    return summary, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only run the first N questions (smoke test)")
    ap.add_argument("--type", choices=["prose", "numeric", "multi-doc"])
    ap.add_argument("--label", default="int4")
    ap.add_argument("--model", help="path or hf id of the model artifact to test")
    ap.add_argument("--out", help="write JSON results here")
    ap.add_argument("--resume", action="store_true",
                    help="skip questions already recorded in bench_<label>.partial.jsonl")
    ap.add_argument("--fresh", action="store_true",
                    help="discard any existing partial file and start over")
    ap.add_argument("--holdout", action="store_true",
                    help="evaluate holdout_set.json instead of gold_set.json (honest "
                         "generalization number: those documents were never inspected while "
                         "diagnosing failures)")
    args = ap.parse_args()

    summary, rows = run_bench(args.limit, args.type, args.label, args.model,
                              resume=args.resume, fresh=args.fresh, holdout=args.holdout)

    print(f"\n=== {summary['label']} ===")
    print(f"  accuracy   {summary['accuracy_overall']}   citation {summary['citation_rate']}")
    for t, b in summary["by_type"].items():
        print(f"    {t:<10} {b['correct']}/{b['n']}  acc={b['accuracy']}  cited={b['cited']}/{b['n']}")
    print(f"  latency    P50 {summary['latency_p50_s']}s  P95 {summary['latency_p95_s']}s")
    print(f"  memory     MLX peak {summary['mlx_peak_gb_max']} GB   "
          f"OS footprint {summary['os_footprint_gb_max']} GB   "
          f"(MLX under-reports by {summary['mlx_vs_os_gap_gb']} GB)")
    print(f"  swap       after {summary['swap_after_mb']} MB   "
          f"max delta {summary['swap_max_delta_mb']} MB")

    out = Path(args.out) if args.out else REPO_ROOT / "results" / f"bench_{args.label}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
