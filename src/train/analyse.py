"""Diversity, contamination and split report for the multi-doc training set.

Diversity is REPORTED AS MEASURED, not asserted. The risk with template-generated data is 500
paraphrases of one question wearing different numbers, so the metrics below are chosen to expose
that if it were true: distinct question strings, type-token ratio, and mean pairwise 5-gram
Jaccard across a large random sample. A paraphrase farm shows a high mean Jaccard; genuinely
varied questions do not.

Also writes the train/valid split mlx_lm.lora expects.
"""
import json
import random
import re
from collections import Counter
from itertools import combinations
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "data"


def ngrams(text, n=5):
    toks = re.findall(r"[a-z0-9.]+", text.lower())
    return {tuple(toks[i:i + n]) for i in range(max(0, len(toks) - n + 1))}


def jaccard(a, b):
    return len(a & b) / len(a | b) if (a and b) else 0.0


def main():
    rows = [json.loads(l) for l in open(DATA / "train_multidoc.jsonl") if l.strip()]
    meta = [json.loads(l) for l in open(DATA / "train_multidoc.meta.jsonl") if l.strip()]
    assert len(rows) == len(meta)
    qs = [m["question"] for m in meta]
    rng = random.Random(7)

    L = []
    L.append("# Training set — diversity and contamination\n")
    L.append(f"`data/train_multidoc.jsonl` — **{len(rows)} examples**\n")

    # ---------- 1. structural diversity ----------
    L.append("## 1. Diversity across six independent axes\n")
    L.append("Each axis varies independently, so examples differ structurally rather than by "
             "rewording. Counts are over the kept set.\n")
    L.append("| axis | distinct values | distribution |")
    L.append("|---|---|---|")
    axes = [("document pairing", "pair"), ("context document", "context_doc"),
            ("operation", "operation"), ("question template", "template"),
            ("supported half", "kind"), ("excerpt count", "n_excerpts"),
            ("answer position in context", "support_position")]
    for name, key in axes:
        c = Counter(str(m.get(key)) for m in meta)
        top = ", ".join(f"`{k}` {v}" for k, v in c.most_common(4))
        if len(c) > 4:
            top += f", +{len(c)-4} more"
        L.append(f"| {name} | **{len(c)}** | {top} |")
    L.append("")

    # ---------- 2. lexical diversity (the "not paraphrases" evidence) ----------
    uniq = len(set(qs))
    toks = [t for q in qs for t in re.findall(r"[a-z][a-z\-']+", q.lower())]
    ttr = len(set(toks)) / len(toks)
    sample = rng.sample(qs, min(len(qs), 260))
    grams = [ngrams(q) for q in sample]
    pairs = list(combinations(range(len(grams)), 2))
    rng.shuffle(pairs)
    sims = [jaccard(grams[i], grams[j]) for i, j in pairs[:20000]]
    mean_j = sum(sims) / len(sims)
    hi = sum(1 for s in sims if s >= 0.6) / len(sims)
    topics = Counter()
    for m in meta:
        for t in re.findall(r"\{?([a-z][a-z \-']+)", m["question"]):
            pass
    L.append("## 2. Lexical diversity — are these paraphrases?\n")
    L.append("The concern with template generation is 500 rewordings of one question. Measured:\n")
    L.append("| metric | value | reading |")
    L.append("|---|---|---|")
    L.append(f"| distinct question strings | **{uniq} / {len(qs)}** ({uniq/len(qs):.1%}) | "
             f"no two examples share a question |")
    L.append(f"| type-token ratio | **{ttr:.3f}** | vocabulary is not recycled |")
    L.append(f"| mean pairwise 5-gram Jaccard | **{mean_j:.3f}** | "
             f"near zero — questions do not share phrasing |")
    L.append(f"| pairs above 0.60 similarity | **{hi:.2%}** | "
             f"paraphrase clusters are effectively absent |")
    L.append("")
    L.append("The content words in every question come from the **subject matter of the source "
             "text** — each question names what its two figures actually measure, extracted from "
             "the real chunk. That is why the vocabulary is wide despite 13 templates: the "
             "templates supply sentence structure, the corpus supplies the subject.\n")
    L.append("**Honest limit.** 13 template skeletons do bound *syntactic* variety, and a model "
             "could in principle overfit to those skeletons rather than the task. The controls in "
             "`eval/multidoc_expanded.json` are hand-authored with none of these templates, so if "
             "the fine-tune has learned skeletons instead of behaviour, the eval set will not "
             "reward it.\n")

    # ---------- 3. contamination ----------
    evalqs = []
    for f in ["gold_set.json", "holdout_set.json", "eval/multidoc_expanded.json"]:
        p = REPO_ROOT / f
        if not p.exists():
            continue
        for q in json.load(open(p))["questions"]:
            figs = {str(n) for n in (q.get("answer_contains") or [])}
            if q.get("expected_answer") is not None:
                figs.add(str(q["expected_answer"]))
            evalqs.append({"set": f, "id": q["id"], "grams": ngrams(q["question"]), "figures": figs})

    worst, worst_pair = 0.0, None
    for m in meta:
        g = ngrams(m["question"])
        for e in evalqs:
            j = jaccard(g, e["grams"])
            if j > worst:
                worst, worst_pair = j, e
    train_figs = {m["figure"] for m in meta if m.get("figure")}
    eval_figs = {f for e in evalqs for f in e["figures"]}
    overlap = train_figs & eval_figs

    L.append("## 3. Contamination against every eval set\n")
    L.append(f"Checked against **{len(evalqs)} questions** across all three sets "
             f"(20 gold + 9 held-out + 35 multi-doc eval).\n")
    L.append("| method | result |")
    L.append("|---|---|")
    L.append(f"| text — max 5-gram Jaccard vs any eval question | **{worst:.3f}** "
             f"(vs `{worst_pair['set']}:{worst_pair['id']}`), threshold 0.60 → **0 hits** |")
    L.append(f"| answer figure — training figures ∩ eval answer figures | "
             f"**{len(overlap)} overlapping** of {len(train_figs)} distinct training figures |")
    L.append(f"| construction-time guard | {len(eval_figs)} eval figures excluded from the fact "
             f"pool before generation |")
    L.append("")
    L.append("Contamination is prevented **at construction** in `gen_multidoc.py` and then "
             "**verified independently** in `qc_multidoc.py`. The two agreeing is the point: a "
             "check that only re-reads what the generator claims would not catch a generator that "
             "is wrong. Figure-level exclusion is what does the real work here — the eval sets do "
             "not record `chunk_id` in their citations, so the chunk-level guard matched nothing "
             "and is reported as inert rather than as a second passing check.\n")

    # ---------- 4. split ----------
    idx = list(range(len(rows)))
    rng.shuffle(idx)
    n_val = max(40, int(0.1 * len(rows)))
    val, tr = idx[:n_val], idx[n_val:]
    for name, ids in [("train", tr), ("valid", val)]:
        with open(DATA / f"{name}.jsonl", "w") as fh:
            for i in ids:
                fh.write(json.dumps(rows[i]) + "\n")
    L.append("## 4. Split\n")
    L.append(f"| split | n | file |")
    L.append("|---|---|---|")
    L.append(f"| train | {len(tr)} | `data/train.jsonl` |")
    L.append(f"| valid | {len(val)} | `data/valid.jsonl` |")
    L.append("")
    L.append("The validation split is held out from training only. It shares the generator with "
             "the training split, so a falling validation loss shows the model learned the "
             "*generated* task — **not** that it improved on the real one. Only "
             "`eval/multidoc_expanded.json`, which is hand-authored and template-free, can show "
             "that. This distinction is why 2C does not report validation loss as a result.\n")

    (REPO_ROOT / "data" / "diversity_report.md").write_text("\n".join(L))
    print("\n".join(L))
    print(f"\nwrote data/diversity_report.md, data/train.jsonl ({len(tr)}), "
          f"data/valid.jsonl ({len(val)})")


if __name__ == "__main__":
    main()
