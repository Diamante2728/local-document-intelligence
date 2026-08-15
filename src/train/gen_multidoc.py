"""Generate multi-doc training examples for the M01/M02 failure pattern.

WHAT FAILURE THIS TARGETS
-------------------------
`answer_multidoc()` retrieves per document, then calls `answer_prose(doc_ids=[one_doc])` with
the FULL compound question. The model therefore sees:

    Excerpts: [only BEA's pages]
    Question: Both BEA and FDIC report ... what does BEA report, and what does FDIC report?

Half that question is unanswerable from the given context, so the model returns NOT_IN_CONTEXT
for ALL of it — including the half sitting in front of it. That is M01 and M02.

The taught behaviour: answer the supported half, and say plainly that the rest is not in this
document. The orchestrator already merges per-document answers; it just never receives anything
to merge.

WHY THE PROMPT SHAPE IS COPIED EXACTLY
--------------------------------------
Training examples are built with the same system prompt (PROSE_SYSTEM) and the same
"Excerpts:\n\n[doc pN] text\n\nQuestion: ..." user shape that src/qa/answer.py builds at
inference. Training on a differently-shaped prompt would teach a behaviour the pipeline never
elicits, and the before/after would measure nothing.

WHY GENUINE NEGATIVES ARE INCLUDED
----------------------------------
# DECISION: ~25% of examples are true negatives whose target IS "NOT_IN_CONTEXT".
Training only on "answer the half you can" would teach the model that NOT_IN_CONTEXT is always
wrong. Stage 1's abstention behaviour is load-bearing — the verification layer and the
confidence signal both depend on the model declining when the context really lacks the fact.
Destroying abstention to fix multi-doc would trade one failure class for a worse one
(confidently-wrong answers, the exact class Stage 1 spent its fix budget eliminating).
The controls in eval/multidoc_expanded.json are what detect that regression.

NO CLOUD APIS. Facts and context text come from the local SQLite chunk store; question phrasings
come from local templates plus a locally-hosted model (mlx). Nothing leaves the machine.
"""
import argparse
import json
import random
import re
import sqlite3
from collections import Counter
from pathlib import Path

from ..eval_match import matches_needle

# When False, the generator's upstream guards are disabled so QC can be measured on its own.
# This exists to prove the QC gate is not tautological: with guards on it rejects ~0%, which is
# only meaningful if we can also show what it catches when defects ARE present. See --no-prefilter.
PREFILTER = True

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "index" / "doc_store.sqlite"

# Copied verbatim from src/qa/answer.py — must stay identical to the inference-time system prompt.
PROSE_SYSTEM = (
    "Answer the question using ONLY the provided excerpts. Quote or closely paraphrase them. "
    "If the excerpts do not contain the answer, reply exactly: NOT_IN_CONTEXT. "
    "Never state a numeric figure that does not appear verbatim in the excerpts. "
    "Keep the answer to 1-3 sentences."
)

DOC_LABEL = {
    "bea_gdp_2024q1_second_estimate": "the BEA GDP release",
    "bea_personal_income_outlays_2024_04": "the BEA personal income report",
    "bea_international_transactions_2024q1": "the BEA international transactions release",
    "fdic_quarterly_banking_profile_2024q1": "the FDIC Quarterly Banking Profile",
    "fed_monetary_policy_report_2024_03": "the Federal Reserve Monetary Policy Report",
    "fed_survey_consumer_finances_2022": "the Fed Survey of Consumer Finances",
    "census_poverty_2022_p60_280": "the Census poverty report",
    "census_ft900_trade_2024_03": "the Census FT-900 trade release",
    "census_housing_vacancies": "the Census housing vacancies report",
    "treasury_monthly_statement_2024_06": "the Treasury monthly statement",
    "eia_short_term_energy_outlook_2025_05": "the EIA Short-Term Energy Outlook",
    "usda_wasde_2026_06": "the USDA WASDE report",
    "usda_agricultural_prices_2025_09": "the USDA agricultural prices report",
    "worldbank_commodity_markets_2025_04": "the World Bank commodity markets outlook",
    "oecd_economic_outlook_116_annex": "the OECD Economic Outlook annex",
    "epa_automotive_trends_2024_exec_summary": "the EPA automotive trends summary",
}

# --- Axis 2: operations. Each shapes a structurally different compound question. ---
OPERATIONS = ["comparison", "aggregation", "contradiction", "lookup_then_combine"]

# --- Axis 3: question templates. STRUCTURALLY distinct, not reworded.
# Each varies what the question asks the model to *do* with the two facts, and how the two
# document references are positioned relative to each other.
TEMPLATES = {
    "comparison": [
        "Both {a} and {b} report figures for this period. What does {a} report for {qa}, and what does {b} report for {qb}?",
        "Compare {qa} in {a} against {qb} in {b}. Give both figures.",
        "Which is larger: {qa} as reported by {a}, or {qb} as reported by {b}? State both values.",
        "{a} and {b} cover different sectors. Report {qa} from the former and {qb} from the latter.",
    ],
    "aggregation": [
        "Using {a} and {b} together, what is the combined picture for {qa} and {qb}?",
        "Add together {qa} from {a} and {qb} from {b}. Show both components.",
        "What total do you get when combining {qa} in {a} with {qb} in {b}?",
    ],
    "contradiction": [
        "Do {a} and {b} agree? Give {qa} from the first and {qb} from the second, then say whether they are consistent.",
        "{a} reports {qa} while {b} reports {qb}. Are these two figures in tension? Quote both.",
        "Check {a} against {b}: state {qa} and {qb}, and flag any discrepancy.",
    ],
    "lookup_then_combine": [
        "First find {qa} in {a}, then find {qb} in {b}, and report both together.",
        "Look up {qa} ({a}) and {qb} ({b}). Present the two values side by side.",
        "I need two numbers: {qa} from {a}, and {qb} from {b}. What are they?",
    ],
}

# --- Axis 6: answer surface forms for the supported half. ---
ANSWER_FORMS = [
    "According to {label} (p{page}), {topic} is {figure}. These excerpts do not cover {other}; that figure is in a different document.",
    "{label} reports {figure} for {topic} (p{page}). The excerpts here contain nothing about {other}.",
    "From p{page} of {label}: {figure}. I can only answer that half — {other} is not in these excerpts.",
    "This document gives {topic} as {figure} (p{page}, {label}). The other part of the question, {other}, is not covered by the text provided.",
    "{figure} — that is {topic} per {label}, p{page}. Nothing in these excerpts addresses {other}.",
]

NEGATIVE_FORMS = ["NOT_IN_CONTEXT"]


# Function words and measurement words that carry no topical content. Kept deliberately small:
# over-stripping produced topics like "rate" that name nothing.
_STOP = {"the", "a", "an", "of", "in", "to", "for", "and", "or", "was", "were", "is", "are",
         "at", "by", "on", "from", "with", "that", "this", "as", "it", "its", "be", "been",
         "percent", "million", "billion", "trillion", "about", "up", "down", "rose", "fell",
         "increased", "decreased", "compared", "than", "were", "had", "has", "have", "which",
         "while", "also", "over", "under", "per", "cent", "approximately", "estimated",
         "roughly", "nearly", "some", "all", "both", "these", "those", "there", "their"}


def _topic_from(sentence, figure):
    """A short natural-language handle for what the figure measures, taken from real text.

    Returns None when no usable topic can be extracted, so the fact is dropped from the pool
    rather than producing a question that reads as nonsense. The first version returned a
    placeholder string instead, which is why 325 of 560 first-pass examples were rejected as
    `degenerate_topic` — a generator defect surfacing as a QC rejection.
    """
    before = sentence.split(figure)[0]
    words = re.findall(r"[A-Za-z][A-Za-z\-']{2,}", before)
    kept = [w for w in words[-9:] if w.lower() not in _STOP]
    if len(kept) < 2:
        return None
    topic = " ".join(kept[-4:]).lower()
    # Must read as a phrase, not a fragment of a header or a citation.
    if len(topic) < 10 or len(topic) > 70:
        return None
    if any(ch.isdigit() for ch in topic):
        return None
    return topic


def load_facts(conn, banned_figures, banned_chunks):
    """Prose chunks containing exactly one clean, distinctive figure, grounded in the store.

    Facts whose figure or chunk appears in ANY eval set are excluded up front — contamination is
    prevented at construction time, not merely detected afterwards.
    """
    NUM = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d{3,})(?![\d.])")

    def is_year(fig):
        # A bare 4-digit year is not a measurement. It recurs on nearly every page of a document,
        # so it can never be attributed to one excerpt, and "what does X report for 2025" is not
        # a question. 151 of 235 QC rejections were years.
        # Same bug class as the Stage 1 router defect, where a bare \d cue fired on every year.
        return re.fullmatch(r"(19|20)\d{2}", fig) is not None

    facts = {}
    for doc, pg, cid, txt in conn.execute("SELECT doc_id,page,chunk_id,text FROM chunks"):
        if cid in banned_chunks:
            continue
        t = " ".join(txt.split())
        if not (150 <= len(t) <= 1200):
            continue
        # First usable figure in the chunk: not a year, not an eval answer, distinctive enough.
        m = next((mm for mm in NUM.finditer(t)
                  if (not PREFILTER or not is_year(mm.group(1)))
                  and mm.group(1) not in banned_figures
                  and len(mm.group(1).replace(",", "").replace(".", "")) >= 3), None)
        if not m:
            continue
        fig = m.group(1)
        # Excerpt window centred on the figure. Truncating the chunk at a fixed 700 chars could
        # cut the supporting figure out of the very excerpt meant to license it (8 such rejections
        # as `ungrounded_figure`), so the window is built around the figure, not the chunk start.
        w0 = max(0, m.start() - 340)
        excerpt = t[w0:m.start() + 360].strip()
        s = max(0, m.start() - 140)
        sent = t[s:m.end() + 140].strip()
        if not re.search(r"[a-z]{4,}", sent):
            continue
        topic = _topic_from(sent, fig)
        if topic is None:
            if PREFILTER:          # unusable topic -> drop; without the guard, emit it for QC
                continue
            topic = "the reported figure"
        if PREFILTER and fig in doc:   # figure is part of the doc_id, not a measurement
            continue
        facts.setdefault(doc, []).append({
            "doc": doc, "page": pg, "chunk_id": cid, "figure": fig,
            "sentence": sent, "text": t, "excerpt": excerpt, "topic": topic,
        })
    return {d: v for d, v in facts.items() if len(v) >= 8}


def build_example(rng, facts, docs, kind):
    """One training example. `kind` is 'first', 'second' (partial support) or 'negative'."""
    da, db = rng.sample(docs, 2)
    fa, fb = rng.choice(facts[da]), rng.choice(facts[db])
    la, lb = DOC_LABEL.get(da, da), DOC_LABEL.get(db, db)

    op = rng.choice(OPERATIONS)
    q = rng.choice(TEMPLATES[op]).format(a=la, b=lb, qa=fa["topic"], qb=fb["topic"])

    if kind == "negative":
        # Context is a THIRD document that supports neither half. Target: abstain.
        pool = [d for d in docs if d not in (da, db)]
        dctx = rng.choice(pool)
        support, other_label = None, None
        # The context must genuinely lack BOTH asked-about figures, or the example teaches the
        # model to abstain when the answer is present — worse than the failure being fixed.
        pool = [f for f in facts[dctx]
                if not PREFILTER or (not matches_needle(f["excerpt"], fa["figure"])
                                     and not matches_needle(f["excerpt"], fb["figure"]))]
        if len(pool) < 2:
            return None
        ctx_facts = rng.sample(pool, min(len(pool), rng.randint(2, 4)))
        answer = rng.choice(NEGATIVE_FORMS)
    else:
        support = fa if kind == "first" else fb
        dctx = support["doc"]
        other_label = lb if kind == "first" else la
        other_topic = fb["topic"] if kind == "first" else fa["topic"]
        # Axis 5: 1-4 distractor excerpts from the SAME document, supporting chunk placed anywhere.
        # Distractors must not themselves contain the supporting figure, or the example cannot
        # teach which excerpt licensed the answer (QC rejects these as `ambiguous_figure`).
        n_dist = rng.randint(1, 4)
        pool = [f for f in facts[dctx]
                if f["chunk_id"] != support["chunk_id"]
                and (not PREFILTER or (not matches_needle(f["excerpt"], support["figure"])
                                       and support["figure"] not in f["doc"]))]
        ctx_facts = rng.sample(pool, min(len(pool), n_dist)) + [support]
        rng.shuffle(ctx_facts)
        answer = rng.choice(ANSWER_FORMS).format(
            label=DOC_LABEL.get(dctx, dctx), page=support["page"], topic=support["topic"],
            figure=support["figure"], other=f"{other_topic} in {other_label}")

    excerpts = [f'[{f["doc"]} p{f["page"]}] {f["excerpt"]}' for f in ctx_facts]
    prompt = "Excerpts:\n\n" + "\n\n".join(excerpts) + f"\n\nQuestion: {q}"

    return {
        "messages": [
            {"role": "system", "content": PROSE_SYSTEM},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": answer},
        ],
        "meta": {
            "kind": kind, "operation": op, "context_doc": dctx,
            "pair": f"{da}|{db}", "n_excerpts": len(ctx_facts),
            "support_position": (ctx_facts.index(support) + 1) if support else None,
            "figure": support["figure"] if support else None,
            # Both asked-about figures, so QC can verify a negative's context really lacks them.
            "asked_figures": [fa["figure"], fb["figure"]],
            "template": rng_template_id(op, q, la, lb, fa, fb),
            "question": q,
        },
    }


def rng_template_id(op, q, la, lb, fa, fb):
    for i, t in enumerate(TEMPLATES[op]):
        if t.format(a=la, b=lb, qa=fa["topic"], qb=fb["topic"]) == q:
            return f"{op}#{i}"
    return f"{op}#?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=560)
    ap.add_argument("--seed", type=int, default=20260815)
    ap.add_argument("--out", default="data/train_multidoc.raw.jsonl")
    ap.add_argument("--no-prefilter", action="store_true",
                    help="disable upstream guards; used to measure QC on its own")
    args = ap.parse_args()
    rng = random.Random(args.seed)
    global PREFILTER
    PREFILTER = not args.no_prefilter
    if not PREFILTER:
        print("PREFILTER OFF — generating an unguarded batch to measure the QC gate")

    # Contamination prevented at construction: collect every figure and chunk any eval set uses.
    banned_figures, banned_chunks = set(), set()
    for f in ["gold_set.json", "holdout_set.json", "eval/multidoc_expanded.json"]:
        p = REPO_ROOT / f
        if not p.exists():
            continue
        blob = json.load(open(p))
        for q in blob.get("questions", []):
            for n in q.get("answer_contains", []) or []:
                banned_figures.add(str(n))
            if q.get("expected_answer") is not None:
                banned_figures.add(str(q["expected_answer"]))
            cits = q.get("expected_citation") or []
            for c in (cits if isinstance(cits, list) else [cits]):
                if isinstance(c, dict) and c.get("chunk_id"):
                    banned_chunks.add(c["chunk_id"])
    print(f"contamination guard: {len(banned_figures)} figures and "
          f"{len(banned_chunks)} chunks excluded from the fact pool up front")

    conn = sqlite3.connect(DB_PATH)
    facts = load_facts(conn, banned_figures, banned_chunks)
    docs = sorted(facts)
    print(f"fact pool: {sum(len(v) for v in facts.values()):,} facts across {len(docs)} documents")

    # Axis 4: which half the context supports. 3:3:2 -> 37.5/37.5/25 partial/partial/negative.
    kinds = ["first", "second", "negative"]
    weights = [3, 3, 2]
    out, seen_q = [], set()
    while len(out) < args.n:
        ex = build_example(rng, facts, docs, rng.choices(kinds, weights)[0])
        if ex is None:      # no clean context available for that draw
            continue
        key = ex["meta"]["question"] + "|" + ex["meta"]["context_doc"]
        if key in seen_q:          # exact duplicate prompt -> drop before it reaches QC
            continue
        seen_q.add(key)
        out.append(ex)

    path = REPO_ROOT / args.out
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        for ex in out:
            fh.write(json.dumps(ex) + "\n")

    print(f"\nwrote {len(out)} raw examples -> {path}")
    for axis in ["kind", "operation", "template", "context_doc"]:
        c = Counter(e["meta"][axis] for e in out)
        print(f"  {axis:<12} {len(c)} distinct   {dict(c.most_common(4))}")
    print(f"  pairs        {len(set(e['meta']['pair'] for e in out))} distinct document pairings")


if __name__ == "__main__":
    main()
