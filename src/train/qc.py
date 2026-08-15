"""2A — quality control and contamination checking for generated training data.

Two jobs, both required by the Stage 2 brief:

  QC            reject examples that are unanswerable, ambiguous, leak their own answer, or are
                built on garbage labels. Reports a rejection rate and keeps every rejected
                example with its reason, so the rejections can be shown rather than summarised.

  CONTAMINATION make sure nothing in the training set overlaps the evaluation sets. Two
                independent methods, because either alone has a blind spot:

                  (a) CELL-LEVEL exclusion — drop any example whose target cell is a cell the
                      gold set or held-out set asks about. Exact, and catches the case where a
                      differently-worded question points at the same answer. Text similarity
                      would miss this entirely.
                  (b) TEXT-LEVEL n-gram overlap — normalised token 5-gram Jaccard against every
                      eval question, rejecting above CONTAM_JACCARD. Catches near-duplicate
                      phrasing even when it targets a different cell.

                (a) is the one that actually matters here: the generator draws from the same 183
                tables the eval questions were written from, so cell collision is likely and
                textual collision is not.

Usage:
    python -m src.train.qc --in data/train_raw.jsonl --out data/train_clean.jsonl
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

CONTAM_JACCARD = 0.6      # 5-gram Jaccard above this counts as contaminated
NGRAM_N = 5
MIN_Q_CHARS, MAX_Q_CHARS = 20, 260
MAX_LABEL_DIGIT_RATIO = 0.4


def norm_tokens(text):
    return [t for t in re.findall(r"[a-z0-9.]+", str(text).lower()) if t]


def ngrams(tokens, n=NGRAM_N):
    if len(tokens) < n:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def load_eval_surfaces():
    """Returns (eval_ngram_sets, eval_cell_keys, eval_questions)."""
    grams, cells, questions = [], set(), []
    for fname in ("gold_set.json", "holdout_set.json"):
        p = REPO_ROOT / fname
        if not p.exists():
            continue
        for q in json.loads(p.read_text())["questions"]:
            questions.append(q["question"])
            grams.append(ngrams(norm_tokens(q["question"])))
            ec = q.get("expected_citation")
            for c in (ec if isinstance(ec, list) else [ec]):
                if not isinstance(c, dict):
                    continue
                # Cell-level key. Gold citations name section/row_label rather than row/col
                # indices, so match on the labels the citation actually carries.
                cells.add((c.get("doc"), c.get("table_id"),
                           (c.get("row_label") or "").strip().lower(),
                           (c.get("section") or "").strip().lower()))
    return grams, cells, questions


def digit_ratio(s):
    s = str(s)
    if not s:
        return 1.0
    return sum(ch.isdigit() for ch in s) / len(s)


def qc_one(ex, eval_grams, eval_cells):
    """Returns list of rejection reasons — empty means the example passes."""
    reasons = []
    q = ex.get("question", "")
    target_ids = set(ex.get("answer_cell_ids", []))
    targets = [c for c in ex["candidates"] if c["id"] in target_ids]

    # --- structural sanity -------------------------------------------------
    if not (MIN_Q_CHARS <= len(q) <= MAX_Q_CHARS):
        reasons.append(f"question length {len(q)} outside [{MIN_Q_CHARS},{MAX_Q_CHARS}]")
    if "{" in q or "}" in q:
        reasons.append("unfilled template placeholder in question")
    if not targets:
        reasons.append("target cell id not present among candidates")

    # --- garbage labels ----------------------------------------------------
    # Merged-cell extraction artefacts produce row labels that are just runs of numbers
    # ("8.8 8.4 7.7 5.9 ..."). A question built on one of those is unanswerable by design.
    for t in targets:
        if digit_ratio(t["row_label"]) > MAX_LABEL_DIGIT_RATIO:
            reasons.append(f"target row_label is mostly digits: {t['row_label'][:40]!r}")
            break

    # --- answer leakage ----------------------------------------------------
    # If the question already contains the value, the model can copy rather than select.
    q_tokens = set(norm_tokens(q))
    for t in targets:
        v = str(t["value"]).lower()
        if v and v in q_tokens:
            reasons.append(f"question leaks the answer value {v!r}")
            break

    # --- ambiguity ---------------------------------------------------------
    # The question must identify exactly ONE candidate. If another candidate shares the target's
    # (row_label, header, section) triple, no answer is uniquely correct and the example teaches
    # the model to guess.
    if targets:
        t = targets[0]
        key = (t["row_label"].lower(), t["header"].lower(), t["section"].lower())
        twins = [c for c in ex["candidates"]
                 if c["id"] not in target_ids
                 and (c["row_label"].lower(), c["header"].lower(), c["section"].lower()) == key]
        if twins:
            reasons.append(f"ambiguous: {len(twins)} other candidate(s) share the same "
                           f"row/column/section labels")
    if ex["operation"] in ("max", "min"):
        # A superlative needs a stated column, or "highest value" is undefined across the table.
        if not any(tok in q.lower() for tok in ("column", "for ", "under ", "among")):
            reasons.append("superlative question does not identify which column to rank within")

    # --- contamination -----------------------------------------------------
    for t in targets:
        key = (ex["doc_id"], ex["table_id"], t["row_label"].strip().lower(),
               t["section"].strip().lower())
        if key in eval_cells:
            reasons.append(f"CONTAMINATION: target cell is used by an eval question ({key[0]} "
                           f"{key[1]} {key[2][:30]!r})")
            break
    g = ngrams(norm_tokens(q))
    for eg in eval_grams:
        j = jaccard(g, eg)
        if j >= CONTAM_JACCARD:
            reasons.append(f"CONTAMINATION: {NGRAM_N}-gram Jaccard {j:.2f} vs an eval question")
            break

    return reasons


def to_training_record(ex):
    """Render a passing example into the prompt/completion form mlx-lm LoRA consumes.

    The prompt mirrors the PRODUCTION planner prompt (src/qa/plan.py) as closely as possible —
    training on a different format than inference uses would teach a behaviour the system never
    exercises.
    """
    lines = [f"Question: {ex['question']}", "", "Candidate cells:"]
    for c in sorted(ex["candidates"], key=lambda c: c["id"]):
        unit = f" {c['unit']}" if c.get("unit") else ""
        sec = f' | section: "{c["section"]}"' if c["section"] else ""
        lines.append(f'  [{c["id"]}] {c["value"]}{unit}  (row: "{c["row_label"]}" | '
                     f'column: "{c["header"]}"{sec})')
    lines.append("")
    lines.append("Return the JSON plan naming the operation and the cell id(s) needed.")
    completion = json.dumps({"operation": ex["operation"], "cells": ex["answer_cell_ids"]})
    return {"prompt": "\n".join(lines), "completion": completion}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="data/train_raw.jsonl")
    ap.add_argument("--out", default="data/train_clean.jsonl")
    ap.add_argument("--rejects", default="data/rejected.jsonl")
    args = ap.parse_args()

    raw = [json.loads(l) for l in (REPO_ROOT / args.inp).read_text().splitlines() if l.strip()]
    eval_grams, eval_cells, eval_qs = load_eval_surfaces()
    print(f"loaded {len(raw)} raw examples")
    print(f"eval surfaces: {len(eval_qs)} questions, {len(eval_cells)} distinct cited cells")

    kept, rejected = [], []
    for ex in raw:
        reasons = qc_one(ex, eval_grams, eval_cells)
        if reasons:
            rejected.append({**ex, "reject_reasons": reasons})
        else:
            kept.append(ex)

    rate = len(rejected) / len(raw) if raw else 0.0
    print(f"\nQC: kept {len(kept)}, rejected {len(rejected)}  "
          f"(rejection rate {rate:.1%})")
    counts = Counter(r["reject_reasons"][0].split(":")[0] for r in rejected)
    for reason, n in counts.most_common():
        print(f"   {n:4d}  {reason}")

    out = REPO_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as fh:
        for ex in kept:
            fh.write(json.dumps(to_training_record(ex)) + "\n")
    with open(REPO_ROOT / args.rejects, "w") as fh:
        for ex in rejected:
            fh.write(json.dumps(ex) + "\n")
    print(f"\nwrote {len(kept)} training records -> {out}")
    print(f"wrote {len(rejected)} rejects (with reasons) -> {REPO_ROOT / args.rejects}")


if __name__ == "__main__":
    main()
