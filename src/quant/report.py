"""Assemble results/quant_table.md from whatever rung evidence actually exists.

Deliberately refuses to invent rows. If a rung was not run, it says so and explains why, rather
than leaving a plausible-looking blank that a reader might mistake for a measurement. The FP16
row is arithmetic by design — that is the honest finding, not a gap.

Usage: python -m src.quant.report
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS = REPO_ROOT / "results"


def load_json(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def fmt(v, suffix="", dash="—"):
    return dash if v is None else f"{v}{suffix}"


def build():
    int4 = load_json(RESULTS / "bench_int4_fixed.json") or load_json(RESULTS / "bench_int4.json")
    int4_base = load_json(RESULTS / "bench_int4.json")
    holdout = load_json(RESULTS / "bench_holdout.json")
    int8_load = load_json(RESULTS / "loadtest_int8.json")

    L = ["# Quantization Ladder — Deliverable 1D\n"]
    L.append("Apple M1, 8 GB unified memory. Qwen2.5-7B-Instruct, `group_size=64` across rungs.\n")

    # ---------------------------------------------------------------- tradeoff table
    L.append("## Tradeoff table\n")
    L.append("| rung | prose | numeric | multi-doc | overall | P50 | P95 | MLX peak | OS footprint | status |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")

    L.append("| **FP16** | — | — | — | — | — | — | — | — | **not run — infeasible by arithmetic** |")

    if int8_load:
        if int8_load.get("loaded") and not int8_load.get("generated"):
            mem = int8_load.get("memory") or {}
            L.append(f"| **INT8** | — | — | — | — | — | — | "
                     f"{fmt(mem.get('mlx_peak_gb'),' GB')} | {fmt(mem.get('os_footprint_gb'),' GB')} | "
                     f"**LOADS, CANNOT GENERATE — Metal OOM** |")
        elif int8_load.get("generated"):
            mem = int8_load.get("memory") or {}
            L.append(f"| **INT8** | not benchmarked | | | | — | — | "
                     f"{fmt(mem.get('mlx_peak_gb'),' GB')} | {fmt(mem.get('os_footprint_gb'),' GB')} | "
                     f"**loaded and generated** (see notes) |")
        else:
            L.append(f"| **INT8** | — | — | — | — | — | — | — | — | "
                     f"**failed: {str(int8_load.get('error'))[:60]}** |")
    else:
        L.append("| **INT8** | — | — | — | — | — | — | — | — | *not yet attempted* |")

    if int4:
        s = int4["summary"]
        bt = s.get("by_type", {})
        def acc(t):
            b = bt.get(t)
            return f"{b['correct']}/{b['n']}" if b else "—"
        L.append(f"| **INT4** | {acc('prose')} | {acc('numeric')} | {acc('multi-doc')} | "
                 f"**{s['accuracy_overall']}** | {fmt(s['latency_p50_s'],'s')} | "
                 f"{fmt(s['latency_p95_s'],'s')} | {fmt(s['mlx_peak_gb_max'],' GB')} | "
                 f"{fmt(s.get('os_footprint_gb_max'),' GB')} | **measured, working rung** |")
    else:
        L.append("| **INT4** | — | — | — | — | — | — | — | — | *run not complete* |")
    L.append("")

    # ---------------------------------------------------------------- FP16
    L.append("## FP16 — ruled out by arithmetic, not attempted\n")
    L.append("- weights: 7.6B params x 2 bytes = **15.2 GB**")
    L.append("- usable memory: **~4.5 GB** (8 GB total, minus ~3.5 GB macOS)")
    L.append("- **shortfall 10.7 GB**, before any KV cache or activations\n")
    L.append("No FP16 latency or accuracy figures appear above. Downloading a 15 GB artifact that "
             "cannot load would only buy the ability to say we tried; an explained empty row is "
             "the honest output, a fabricated one would not be. Full working in "
             "`results/kv_math.md`.\n")

    # ---------------------------------------------------------------- INT8
    L.append("## INT8 — attempted for real\n")
    if not int8_load:
        L.append("_Not yet attempted._\n")
    else:
        L.append(f"- artifact: `{int8_load.get('repo')}`")
        L.append(f"- loaded: **{int8_load.get('loaded')}**, generated: **{int8_load.get('generated')}**")
        if int8_load.get("load_s"):
            L.append(f"- load time: {int8_load['load_s']}s")
        if int8_load.get("tok_per_s"):
            L.append(f"- throughput: **{int8_load['tok_per_s']} tok/s**")
        if int8_load.get("error"):
            L.append(f"- error: `{int8_load['error']}`")
        sd = int8_load.get("swap_delta_mb")
        if sd is not None:
            L.append(f"- swap: {int8_load.get('swap_before_mb')} MB -> "
                     f"{int8_load.get('swap_after_mb')} MB (**delta {sd:+.1f} MB**)")
        mem = int8_load.get("memory") or {}
        if mem:
            L.append(f"- MLX peak {fmt(mem.get('mlx_peak_gb'),' GB')}, "
                     f"OS footprint {fmt(mem.get('os_footprint_gb'),' GB')}")
        L.append("")
        L.append("Arithmetic said INT8 weights are **7.6 GB against ~4.5 GB usable**, i.e. it "
                 "should not fit. What actually happened is recorded above rather than predicted.\n")

    # ---------------------------------------------------------------- INT4 detail
    if int4:
        s = int4["summary"]
        L.append("## INT4 — the working rung\n")
        L.append(f"- overall accuracy **{s['accuracy_overall']}**, citation rate "
                 f"**{s['citation_rate']}**")
        for t, b in s.get("by_type", {}).items():
            L.append(f"  - {t}: **{b['correct']}/{b['n']}** (acc {b['accuracy']}), "
                     f"cited {b['cited']}/{b['n']}")
        L.append(f"- latency P50 **{s['latency_p50_s']}s**, P95 **{s['latency_p95_s']}s**, "
                 f"mean {s['latency_mean_s']}s, wall clock {s['wall_clock_s']}s")
        L.append(f"- MLX peak **{s['mlx_peak_gb_max']} GB**, OS footprint "
                 f"**{s.get('os_footprint_gb_max')} GB** "
                 f"(MLX under-reports by {s.get('mlx_vs_os_gap_gb')} GB)")
        L.append(f"- swap after run {s.get('swap_after_mb')} MB, "
                 f"max single-question delta {s.get('swap_max_delta_mb')} MB\n")

    # ---------------------------------------------------------------- caveats
    L.append("## Caveats that qualify every number above\n")
    L.append("1. **P95 measures swap, not model speed.** This machine swaps under load; a single "
             "question was observed at 494 s against a ~90 s median, and `ps` itself failed with "
             "*sysmond service not found* during one run. Treat P50 as the model characteristic "
             "and P95 as a memory-pressure characteristic.")
    L.append("2. **`ps` RSS is unusable on Metal** — ~50 MB reported against ~5.6 GB `footprint` "
             "for the same loaded model, because unified-memory buffers are not counted in RSS. "
             "Both MLX and `footprint` figures are reported; the measured gap was 0.31-0.68 GB, "
             "**not** the ~2x the build spec anticipated.")
    L.append("3. **Only one rung ran**, so per-type accuracy describes *this system*, not *this "
             "precision*. Numeric errors concentrated in column selection (real cells, wrong "
             "column), but with a single rung that cannot be attributed to INT4.")
    L.append("4. **The INT8 artifact is pre-quantized, not locally converted.** "
             "`mlx-community/Qwen2.5-7B-Instruct-8bit` reports `group_size=64`, matching the "
             "4-bit exactly, with identical 28 layers / 4 KV heads — genuinely the same model at "
             "two precisions. Local conversion would have needed ~23 GB against ~30 GB free on "
             "an already-swapping disk.")
    L.append("5. **Multi-doc scores 0/4 for structural reasons, not quantization.** Three "
             "designs were tried and each failed differently; see `AI_LOG.md`. Its scores drag "
             "the overall number down and should be read separately from prose/numeric.")
    L.append("6. **A GPU OOM was observed** (`kIOGPUCommandBufferCallbackErrorOutOfMemory`) when "
             "the 7B INT4 model and the 130 MB embedding model were on the GPU concurrently. "
             "That was self-inflicted during debugging, but it is real evidence about the "
             "memory ceiling.\n")

    # ---------------------------------------------------------------- recommendation
    L.append("## Deployment recommendation\n")
    L.append("**Ship INT4. On an 8 GB M1 it is not the best rung, it is the only one.**\n")
    L.append("- FP16 is short by 10.7 GB — not a tuning problem, an arithmetic one.")
    L.append("- INT8 needs 7.6 GB of weights against ~4.5 GB usable; see the measured result above.")
    L.append("- INT4 runs at ~4.4-5.9 GB peak depending on path, which already touches swap.\n")
    L.append("Operational notes that follow from the measurements rather than from taste:\n")
    L.append("- **Do not co-locate other GPU work.** The 7B model plus a 130 MB embedding model "
             "was enough to fail the Metal allocator.")
    L.append("- **Concurrency is single-digit.** KV cache is 56 KB/token; at 4k context only "
             "**2 users** fit alongside the weights. 50 concurrent users needs ~15.7 GB against "
             "~4.5 GB usable — roughly 3.5x over budget. That means a bigger machine or "
             "horizontal scaling, not tuning.")
    L.append("- **Budget for P95, not P50.** Swap turns a ~90 s question into a ~500 s question "
             "with no warning.")
    L.append("- Keep context small and cap `--max-kv-size`; KV cache is the term that scales "
             "with users, and it is the one that will exhaust memory first.\n")
    return "\n".join(L)


if __name__ == "__main__":
    out = build()
    dest = RESULTS / "quant_table.md"
    dest.write_text(out)
    print(out)
    print(f"\n[written to {dest}]")
