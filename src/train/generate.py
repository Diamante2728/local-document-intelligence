"""2A — training data construction for the numeric cell-selection failure class.

WHY THIS FAILURE CLASS (from Stage 1's measured taxonomy, not a guess):

    type       accuracy   misses
    multi-doc   1/4       M01 M02 M03    <- worst by rate
    numeric     4/8       N02 N03 N05 N08 <- worst by count
    prose       6/8       P04 P07

Multi-doc is worse by rate, but `results/fix_attempt_analysis.md` measured that **7 of 9 total
failures are post-retrieval** — the correct evidence was already in the model's context and the
model failed to use it. For multi-doc specifically, 2 of 4 failures are retrieval/routing
problems that a LoRA cannot touch. Training against those would be training against a defect the
method cannot fix.

Numeric cell selection is the right target because all four of its misses share one measured
shape: **the correct cell was present in the enumerated candidate list and the planner chose a
different one** (verified 4/4 in fix_attempt_analysis.md). That is purely model behaviour, which
is what LoRA can move.

DIVERSITY STRATEGY — six independent axes, so this is not 500 paraphrases:

  1. SOURCE      183 usable tables across 16 documents spanning banking, trade, agriculture,
                 energy, macro and demography. Different vocabularies, not one domain.
  2. OPERATION   lookup / diff / ratio / pct_change / sum / max / min — the plan's answer shape
                 changes, not just its wording.
  3. DISTRACTOR  the hard part of this task is which WRONG cells sit beside the right one. Four
                 structured distractor regimes are sampled deliberately:
                   same-row-different-column   (the N04/N05 failure: 0.46 vs 498.5)
                   same-column-different-row
                   same-section-different-row
                   same-row-label-different-section (the section-ambiguity failure that produced
                                                     a confidently wrong 0.38 in Stage 1)
  4. LIST SIZE   10 / 20 / 40 candidates shown, so the model does not learn a fixed list length.
  5. PHRASING    a LOCAL model (Qwen2.5-7B-Instruct-4bit) rewrites each templated question into
                 natural language, seeded from several instruction families.
  6. ANSWER POS  the correct cell id is uniformly redistributed across the list, so position is
                 not a learnable shortcut.

Everything is grounded in REAL extracted cells from the Stage 1 store — the model invents the
question phrasing, never the table, the value, or the label. A synthetic pipeline that invented
cell values would be training the model on data the corpus does not contain.

Usage:
    python -m src.train.generate --target 550 --out data/train_raw.jsonl
"""
import argparse
import json
import random
import re
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

OPERATIONS = ["lookup", "lookup", "lookup", "diff", "ratio", "pct_change", "sum", "max", "min"]
LIST_SIZES = [10, 20, 40]
DISTRACTOR_REGIMES = [
    "same_row_other_col",
    "same_col_other_row",
    "same_section_other_row",
    "same_label_other_section",
]

# Template families. These are SCAFFOLDING for the local model to rewrite, not the final text —
# using them verbatim would produce exactly the 500-paraphrases failure the spec calls out.
TEMPLATES = {
    "lookup": [
        "What was the {row} figure for {col}{sec}?",
        "According to {doc}, what is the value of {row} under {col}{sec}?",
        "Report the {row} number for {col}{sec}.",
    ],
    "diff": [
        "How much higher is {row} for {colA} than for {colB}{sec}?",
        "What is the difference between {rowA} and {rowB}{sec}?",
    ],
    "ratio": ["What is the ratio of {rowA} to {rowB}{sec}?"],
    "pct_change": ["What percent change is {rowA} relative to {rowB}{sec}?"],
    "sum": ["What is the combined total of {rowA} and {rowB}{sec}?"],
    # max/min MUST name the column they rank within. An earlier version omitted it and QC
    # correctly rejected every one as unanswerable ("highest value" across a whole table is
    # undefined) — 7 of 60 in the first smoke batch. Fixed at the source rather than generating
    # known-bad examples and paying to reject them.
    "max": ["Which row has the highest value under {col}{sec}?"],
    "min": ["Which row has the lowest value under {col}{sec}?"],
}

REWRITE_SYSTEM = (
    "You rewrite a data-lookup question so it sounds like a real analyst asked it. "
    "Keep every entity name, number, unit and qualifier EXACTLY as given — you may only change "
    "sentence structure and connecting words. Never invent facts, never add figures, never "
    "answer the question. Reply with the rewritten question only, one line, no preamble."
)


def _clean(s, n=60):
    return " ".join(str(s or "").split())[:n]


def load_candidate_tables(conn, min_cells=4):
    from ..qa.table_index import list_numeric_cells
    tm = json.loads((REPO_ROOT / "index" / "table_map.json").read_text())
    out = []
    for t in tm:
        cells = list_numeric_cells(conn, t["doc_id"], t["table_id"], limit=500)
        good = [c for c in cells if len(c["row_label"]) > 5 and (c["header"] or c["section"])]
        if len(good) >= min_cells:
            out.append({**t, "cells": good})
    return out


def pick_distractors(target, cells, regime, k):
    """Choose plausible wrong answers under a named structural regime."""
    pool = [c for c in cells if (c["row"], c["col"]) != (target["row"], target["col"])]
    if regime == "same_row_other_col":
        pref = [c for c in pool if c["row"] == target["row"]]
    elif regime == "same_col_other_row":
        pref = [c for c in pool if c["col"] == target["col"]]
    elif regime == "same_section_other_row":
        pref = [c for c in pool if c["section"] == target["section"]]
    else:  # same_label_other_section — the hardest, and the Stage 1 confidently-wrong case
        pref = [c for c in pool if c["row_label"] == target["row_label"]
                and c["section"] != target["section"]]
    rest = [c for c in pool if c not in pref]
    random.shuffle(pref)
    random.shuffle(rest)
    return (pref + rest)[:k]


def build_example(table, cells, rng):
    """Returns a raw example dict, or None if this table cannot support a clean one."""
    op = rng.choice(OPERATIONS)
    n_list = rng.choice(LIST_SIZES)
    regime = rng.choice(DISTRACTOR_REGIMES)

    multi = op in ("diff", "ratio", "pct_change", "sum")
    targets = []
    if multi:
        pool = [c for c in cells if c["row_label"]]
        if len(pool) < 2:
            return None
        a = rng.choice(pool)
        others = [c for c in pool if c["row_label"] != a["row_label"] and c["col"] == a["col"]]
        if not others:
            return None
        targets = [a, rng.choice(others)]
    elif op in ("max", "min"):
        same_col = [c for c in cells if c["col"] == rng.choice(cells)["col"]]
        if len(same_col) < 3:
            return None
        # key= is required: on tied values Python would fall through to comparing the dicts.
        vals = [(float(c["value"]), c) for c in same_col]
        best = max(vals, key=lambda x: x[0]) if op == "max" else min(vals, key=lambda x: x[0])
        targets = [best[1]]
    else:
        targets = [rng.choice(cells)]

    primary = targets[0]

    # Reject degenerate labels at the SOURCE. Merged-cell extraction artefacts leave row labels
    # that are runs of numbers ("8.8 8.4 7.7 5.9 ..."); a question built on one is unanswerable.
    # QC catches these anyway, but generating them wastes a local-model rewrite call each.
    for t in targets:
        lbl = t["row_label"]
        if not lbl or sum(ch.isdigit() for ch in lbl) / max(len(lbl), 1) > 0.4:
            return None

    distractors = pick_distractors(primary, cells, regime, n_list - len(targets))
    shown = targets + distractors
    if len(shown) < 4:
        return None
    # Uniqueness: the question must identify exactly one candidate. If a distractor shares the
    # target's (row_label, header, section) triple there is no uniquely correct answer, and the
    # example would teach the model to guess. Drop those distractors rather than the example.
    key = (primary["row_label"].lower(), primary["header"].lower(), primary["section"].lower())
    shown = targets + [
        c for c in distractors
        if (c["row_label"].lower(), c["header"].lower(), c["section"].lower()) != key
    ]
    if len(shown) < 4:
        return None

    rng.shuffle(shown)                      # answer position is not a shortcut
    ids = {(c["row"], c["col"]): i + 1 for i, c in enumerate(shown)}

    sec = f" in {_clean(primary['section'], 40)}" if primary["section"] else ""
    tpl = rng.choice(TEMPLATES[op])
    q = tpl.format(
        row=_clean(primary["row_label"], 40), rowA=_clean(targets[0]["row_label"], 40),
        rowB=_clean(targets[-1]["row_label"], 40) if len(targets) > 1 else "",
        col=_clean(primary["header"], 40) or "that column",
        colA=_clean(targets[0]["header"], 30), colB=_clean(targets[-1]["header"], 30),
        sec=sec, doc=table["doc_id"].replace("_", " ")[:40],
    )
    q = re.sub(r"\s+", " ", q).replace(" .", ".").strip()

    return {
        "doc_id": table["doc_id"], "table_id": table["table_id"], "page": table["page"],
        "operation": op, "regime": regime, "n_candidates": len(shown),
        "template_question": q,
        "answer_cell_ids": [ids[(t["row"], t["col"])] for t in targets],
        "answer_values": [t["value"] for t in targets],
        "candidates": [
            {"id": ids[(c["row"], c["col"])], "value": c["value"], "unit": c["unit"],
             "row_label": _clean(c["row_label"]), "header": _clean(c["header"], 50),
             "section": _clean(c["section"], 50), "row": c["row"], "col": c["col"]}
            for c in shown
        ],
    }


def rewrite_batch(examples, batch_log=None):
    """Diversify phrasing with the LOCAL model. Falls back to the template on any failure."""
    from ..qa.llm import generate_text
    for i, ex in enumerate(examples):
        try:
            out, _ = generate_text(
                f"Rewrite this question:\n{ex['template_question']}",
                max_tokens=70, system=REWRITE_SYSTEM,
            )
            cand = " ".join(out.strip().splitlines()[0].split())
            cand = cand.strip('"').strip()
            ex["question"] = cand if 15 <= len(cand) <= 260 else ex["template_question"]
            ex["rewritten"] = ex["question"] != ex["template_question"]
        except Exception as e:
            ex["question"] = ex["template_question"]
            ex["rewritten"] = False
            ex["rewrite_error"] = f"{type(e).__name__}: {e}"
        if batch_log and (i + 1) % 25 == 0:
            print(f"  rewritten {i+1}/{len(examples)}", flush=True)
    return examples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=550)
    ap.add_argument("--out", default="data/train_raw.jsonl")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--no-rewrite", action="store_true",
                    help="skip the local-model rewrite pass (templates only, for fast testing)")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    conn = sqlite3.connect(REPO_ROOT / "index" / "doc_store.sqlite")
    tables = load_candidate_tables(conn)
    print(f"usable tables: {len(tables)} across "
          f"{len({t['doc_id'] for t in tables})} documents")

    raw, attempts = [], 0
    while len(raw) < args.target and attempts < args.target * 40:
        attempts += 1
        t = rng.choice(tables)
        ex = build_example(t, t["cells"], rng)
        if ex:
            raw.append(ex)
    print(f"generated {len(raw)} raw examples in {attempts} attempts")

    if not args.no_rewrite:
        print("rewriting phrasing with the local model (this is the slow part)...")
        raw = rewrite_batch(raw, batch_log=True)
    else:
        for ex in raw:
            ex["question"] = ex["template_question"]
            ex["rewritten"] = False

    out = REPO_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as fh:
        for ex in raw:
            fh.write(json.dumps(ex) + "\n")
    print(f"wrote {len(raw)} -> {out}")


if __name__ == "__main__":
    main()
