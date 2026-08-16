"""Assemble results/stage2_comparison.md from the per-arm result files.

Reports what was measured. The verdict line is computed from the numbers, not written in advance:
if the prompted-only arm matches or beats the fine-tune, this says so.
"""
import json
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RES = REPO_ROOT / "results"
ARM_LABEL = {
    "base": "1. base 3B (pipeline unchanged)",
    "tuned": "2. fine-tuned 3B (LoRA r8)",
    "prompted": "3. base 3B + decomposition + few-shot",
}


def load(name):
    p = RES / name
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def pct(c, n):
    return f"{c}/{n} ({c/n:.1%})" if n else "—"


def build_report():
    arms = {a: load(f"stage2_{a}.jsonl") for a in ARM_LABEL}
    arms = {a: r for a, r in arms.items() if r}
    if not arms:
        print("no arm results found")
        return

    L = ["# Stage 2C — three-arm comparison", ""]
    L.append("All arms run the **same** `Qwen2.5-3B-Instruct-4bit` base, so the only difference is "
             "the intervention. The multi-doc path is forced for every question: all 35 are known "
             "multi-doc, and routing errors are not LoRA-trainable (`results/failure_split.md`), "
             "so including them would confound the variable under test.")
    L.append("")

    # ---- headline ----
    L.append("## (i) Hand-authored eval set — the only real measure")
    L.append("")
    L.append("| arm | strict accuracy | partial credit | mean latency |")
    L.append("|---|---|---|---|")
    summary = {}
    for a, rows in arms.items():
        c = sum(r["correct"] for r in rows)
        n = len(rows)
        part = sum(r["partial"] for r in rows) / n
        lat = sum(r["latency_s"] for r in rows) / n
        summary[a] = {"correct": c, "n": n, "acc": c / n, "partial": part}
        L.append(f"| {ARM_LABEL[a]} | **{pct(c, n)}** | {part:.3f} | {lat:.0f}s |")
    L.append("")
    L.append("*Strict* = every required figure present. *Partial* = mean fraction of required "
             "figures present; it separates \"moved from 0 to 1 of 2 figures\" from \"changed "
             "nothing\", but only strict accuracy answers the question that was asked.")
    L.append("")

    # ---- by cross-doc vs control ----
    L.append("### Cross-document vs same-document controls")
    L.append("")
    L.append("| arm | cross-document (26) | same-doc control (9) |")
    L.append("|---|---|---|")
    for a, rows in arms.items():
        x = [r for r in rows if r["xdoc"]]
        c_ = [r for r in rows if not r["xdoc"]]
        L.append(f"| {ARM_LABEL[a]} | {pct(sum(r['correct'] for r in x), len(x))} | "
                 f"{pct(sum(r['correct'] for r in c_), len(c_))} |")
    L.append("")
    L.append("The controls exist to tell a *multi-document reasoning* gain apart from a generic "
             "two-fact-extraction gain. A win on cross-document that leaves controls flat is the "
             "former; a win on both is the latter.")
    L.append("")

    # ---- by operation ----
    ops = sorted({r["operation"] for rows in arms.values() for r in rows if r.get("operation")})
    L.append("### By operation")
    L.append("")
    L.append("| arm | " + " | ".join(ops) + " |")
    L.append("|---|" + "---|" * len(ops))
    for a, rows in arms.items():
        cells = []
        for op in ops:
            sel = [r for r in rows if r.get("operation") == op]
            cells.append(pct(sum(r["correct"] for r in sel), len(sel)))
        L.append(f"| {ARM_LABEL[a]} | " + " | ".join(cells) + " |")
    L.append("")

    # ---- regression ----
    L.append("## (ii) Regression — did the adapter damage anything else?")
    L.append("")
    arc = {a: load(f"regress_arc_{a}.jsonl") for a in ("base", "tuned")}
    if any(arc.values()):
        L.append("### ARC (general reasoning, unrelated to this corpus)")
        L.append("")
        L.append("| split | base | fine-tuned | delta |")
        L.append("|---|---|---|---|")
        splits = sorted({r["split"] for rows in arc.values() for r in rows})
        for sp in splits + ["OVERALL"]:
            vals = {}
            for a in ("base", "tuned"):
                sel = [r for r in arc[a] if sp == "OVERALL" or r["split"] == sp]
                vals[a] = (sum(r["correct"] for r in sel), len(sel))
            if not vals["base"][1] or not vals["tuned"][1]:
                continue
            b = vals["base"][0] / vals["base"][1]
            t = vals["tuned"][0] / vals["tuned"][1]
            d = t - b
            L.append(f"| {sp} | {pct(*vals['base'])} | {pct(*vals['tuned'])} | "
                     f"**{d:+.1%}** |")
        L.append("")

    s1 = {a: load(f"regress_stage1_{a}.jsonl") for a in ("base", "tuned")}
    if any(s1.values()):
        L.append("### Stage 1 prose / numeric questions (real pipeline)")
        L.append("")
        L.append("| type | base | fine-tuned | delta |")
        L.append("|---|---|---|---|")
        types = sorted({r["type"] for rows in s1.values() for r in rows})
        for ty in types + ["OVERALL"]:
            vals = {}
            for a in ("base", "tuned"):
                sel = [r for r in s1[a] if ty == "OVERALL" or r["type"] == ty]
                vals[a] = (sum(r["correct"] for r in sel), len(sel))
            if not vals["base"][1] or not vals["tuned"][1]:
                continue
            b = vals["base"][0] / vals["base"][1]
            t = vals["tuned"][0] / vals["tuned"][1]
            L.append(f"| {ty} | {pct(*vals['base'])} | {pct(*vals['tuned'])} | "
                     f"**{t-b:+.1%}** |")
        L.append("")

    # ---- verdict, computed ----
    L.append("## (iii) Verdict")
    L.append("")
    if "tuned" in summary and "prompted" in summary and "base" in summary:
        t, p, b = summary["tuned"], summary["prompted"], summary["base"]
        L.append(f"- base **{b['acc']:.1%}** · fine-tuned **{t['acc']:.1%}** · "
                 f"prompted-only **{p['acc']:.1%}**")
        L.append("")
        if p["acc"] > t["acc"]:
            L.append("**The prompted-only baseline BEATS the fine-tune.** Recorded as the outcome "
                     "pre-registered in `results/eval_expansion_notes.md`: the multi-doc failures "
                     "were a prompt-construction defect, and fine-tuning was not the right tool "
                     "for them.")
        elif p["acc"] == t["acc"]:
            L.append("**The prompted-only baseline MATCHES the fine-tune.** Since prompting costs "
                     "no training, no adapter and no regression risk, matching is a win for "
                     "prompting — this is the pre-registered outcome.")
        else:
            L.append(f"**The fine-tune beats the prompted-only baseline** "
                     f"({t['acc']:.1%} vs {p['acc']:.1%}). The baseline was given equal effort "
                     f"(real few-shot examples and real per-document decomposition applied before "
                     f"retrieval), so this is a fair comparison rather than a strawman.")
    L.append("")
    (RES / "stage2_comparison.md").write_text("\n".join(L))
    print("\n".join(L))
    print(f"\nwrote {RES / 'stage2_comparison.md'}")


if __name__ == "__main__":
    build_report()
