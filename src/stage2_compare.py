"""Stage 2C — three-arm comparison on the hand-authored multi-doc eval set.

    python -m src.stage2_compare --arm base            # arm 1
    python -m src.stage2_compare --arm tuned           # arm 2
    python -m src.stage2_compare --arm prompted        # arm 3
    python -m src.stage2_compare --report              # combine into results/stage2_comparison.md

ARMS
  1 base      Qwen2.5-3B-Instruct-4bit, pipeline unchanged (compound question per document)
  2 tuned     same + the LoRA adapter from 2B
  3 prompted  base model + per-document decomposition + few-shot, NO fine-tune

All three run the SAME 3B base so the only difference is the intervention. Stage 1 shipped on the
7B; using it here would confound the comparison with model size.

WHY THE MULTI-DOC PATH IS FORCED
Every question in eval/multidoc_expanded.json is known to be multi-doc, and the intervention under
test acts inside `answer_multidoc`. Letting the router decide would mix in routing errors, which
`results/failure_split.md` already established are NOT LoRA-trainable (H09). Forcing the path
isolates the variable being tested. Router behaviour is measured separately and reported alongside,
not silently dropped.

CHECKPOINTED. A full arm is ~35 questions x ~20 s; results are flushed per question so an
interrupted run resumes instead of starting over (the same lesson that cost 19 of 20 questions in
Stage 1).
"""
import argparse
import json
import signal
import time
from collections import defaultdict
from pathlib import Path

from .eval_match import missing_needles

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL = REPO_ROOT / "eval" / "multidoc_expanded.json"
ADAPTER = REPO_ROOT / "results" / "adapters" / "multidoc_r8"
BASE_3B = "mlx-community/Qwen2.5-3B-Instruct-4bit"

ARMS = {
    "base":     {"adapter": None,           "decompose": False, "fewshot": False},
    "tuned":    {"adapter": str(ADAPTER),   "decompose": False, "fewshot": False},
    "prompted": {"adapter": None,           "decompose": True,  "fewshot": True},
}


def configure(arm):
    """Point the shared model wrapper and pipeline flags at one arm's configuration."""
    from .qa import llm as llm_mod
    from .qa import answer as answer_mod
    cfg = ARMS[arm]
    llm_mod.MODEL_ID = BASE_3B
    # Keyed cache: switching arms must reload, or an arm reports the previous arm's numbers.
    llm_mod.ADAPTER_PATH = cfg["adapter"]
    answer_mod.MULTIDOC_DECOMPOSE = cfg["decompose"]
    answer_mod.PROSE_FEWSHOT = cfg["fewshot"]
    llm_mod.cache_limit_gb(1.0)                       # cap MLX buffer cache (see free_gpu_cache)
    llm_mod.get_llm(BASE_3B, cfg["adapter"])          # force the load now, not mid-question
    return cfg


class QuestionTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise QuestionTimeout()


# Per-question wall-clock cap. Normal range on this machine is 65-170 s; 420 s is ~2.5x the
# slowest healthy question.
#
# WHY: peak MLX memory sits at 5.61 GB against a 5.73 GB Metal working set, so a question whose
# retrieved context is slightly larger than usual tips the machine into swap and slows by ~10x.
# X25 did exactly that and blocked the entire 7-job sequence twice, for 18 minutes each time.
# Retrieval parameters are deliberately NOT changed to avoid it — that would alter the system
# under test mid-experiment. Instead the question is recorded as a timeout and the run continues,
# so one pathological question costs one data point instead of the whole comparison.
QUESTION_TIMEOUT_S = 420


def _mem_gb():
    """MLX active + cache memory, recorded per question so cache regrowth shows up as DATA.

    NOT ru_maxrss. Stage 1 already established that Metal unified-memory buffers do not appear in
    RSS (~50 MB RSS measured against a 5.6 GB real footprint), and the first version of this
    function used ru_maxrss anyway — reporting 0.74 GB for a process holding a 3B model. The
    quantity that matters is what MLX itself is holding.
    """
    try:
        import mlx.core as mx
        g = 1024 ** 3
        return {"active": round(mx.get_active_memory() / g, 2),
                "cache": round(mx.get_cache_memory() / g, 2),
                "peak": round(mx.get_peak_memory() / g, 2)}
    except Exception:
        return None


def is_xdoc(q):
    c = q.get("expected_citation")
    return isinstance(c, list) and len({x["doc"] for x in c}) >= 2


def partial_credit(answer_text, needles):
    """Fraction of required figures present. Reported ALONGSIDE strict accuracy, never instead.

    Strict accuracy (all figures present) is the headline because a multi-doc answer that gets one
    of two figures has not answered the question. Partial credit is reported because it separates
    "moved from 0 to 1 of 2 figures" from "changed nothing at all" — the difference between a
    partially working intervention and a dead one.
    """
    if not needles:
        return 0.0
    return (len(needles) - len(missing_needles(answer_text, needles))) / len(needles)


def run_arm(arm, limit=None, resume=True):
    from .qa import answer as answer_mod
    cfg = configure(arm)
    qs = json.load(open(EVAL))["questions"]
    if limit:
        qs = qs[:limit]

    out_path = REPO_ROOT / "results" / f"stage2_{arm}.jsonl"
    done = {}
    if resume and out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                try:
                    r = json.loads(line)
                    done[r["id"]] = r
                except json.JSONDecodeError:
                    pass
        if done:
            print(f"[{arm}] resuming: {len(done)} already complete")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    from .qa.llm import free_gpu_cache
    conn, pi, pm, ti, tm = answer_mod.load_resources()
    rows = []
    for i, q in enumerate(qs, 1):
        if q["id"] in done:
            rows.append(done[q["id"]])
            continue
        free_gpu_cache()          # start each question from a clean cache, not just end it
        t0 = time.perf_counter()
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(QUESTION_TIMEOUT_S)
        try:
            # Path forced — see module docstring.
            res = answer_mod.answer_multidoc(q["question"], conn, pi, pm, ti, tm)
            err = None
        except QuestionTimeout:
            res = {"answer": "", "citations": [], "notes": []}
            err = f"TIMEOUT after {QUESTION_TIMEOUT_S}s"
        except Exception as e:
            res, err = {"answer": "", "citations": [], "notes": []}, f"{type(e).__name__}: {e}"
        finally:
            signal.alarm(0)
        ans = str(res.get("answer", ""))
        miss = missing_needles(ans, q["answer_contains"])
        row = {
            "id": q["id"], "arm": arm, "operation": q.get("operation"),
            "xdoc": is_xdoc(q), "correct": (not miss) and err is None,
            "partial": round(partial_credit(ans, q["answer_contains"]), 3),
            "missing": miss, "answer": ans[:400],
            "n_docs_contributing": len({c.get("doc") for c in res.get("citations", []) or []}),
            "confidence": res.get("confidence"), "path": res.get("path_taken"),
            "latency_s": round(time.perf_counter() - t0, 2), "error": err,
            "mem_gb": _mem_gb(),
        }
        rows.append(row)
        with open(out_path, "a") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
            fh.flush()
        free_gpu_cache()      # MLX buffer cache grows monotonically otherwise -> swap thrash
        mark = "OK " if row["correct"] else "MISS"
        print(f"  [{i}/{len(qs)}] {q['id']:<4} {mark} partial={row['partial']:.2f} "
              f"{row['latency_s']:6.1f}s  miss={miss}")
    acc = sum(r["correct"] for r in rows) / len(rows) if rows else 0
    print(f"[{arm}] accuracy {acc:.3f} ({sum(r['correct'] for r in rows)}/{len(rows)})")
    return rows


def breakdown(rows):
    """Accuracy by operation and by cross-doc vs control."""
    by_op, by_kind = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for r in rows:
        by_op[r["operation"]][0] += int(r["correct"])
        by_op[r["operation"]][1] += 1
        k = "cross-document" if r["xdoc"] else "same-doc control"
        by_kind[k][0] += int(r["correct"])
        by_kind[k][1] += 1
    return by_op, by_kind


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=list(ARMS))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    if args.arm:
        if args.fresh:
            p = REPO_ROOT / "results" / f"stage2_{args.arm}.jsonl"
            p.unlink(missing_ok=True)
        run_arm(args.arm, args.limit, resume=not args.fresh)
        return

    if args.report:
        from .stage2_report import build_report
        build_report()
        return
    ap.print_help()


if __name__ == "__main__":
    main()
