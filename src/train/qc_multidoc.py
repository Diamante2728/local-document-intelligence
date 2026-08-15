"""QC and contamination gate for the multi-doc training set.

Every check here exists because the corresponding defect would teach the model something wrong:

  ungrounded_figure   answer states a figure not verbatim in its own context -> teaches
                      hallucination, the exact behaviour Stage 1's system prompt forbids
  leaked_other_half   the OTHER document's figure appears in this single-doc context -> the
                      example's target ("not covered here") is then factually false
  ambiguous_figure    the answer's figure also appears in a distractor excerpt -> the model
                      cannot learn which excerpt licensed the answer
  degenerate_topic    topic extraction fell back to a placeholder -> question reads as nonsense
  negative_is_false   a 'negative' example whose context DOES contain a required figure ->
                      teaches the model to abstain when the answer is present (worse than M01)
  too_long            exceeds the training sequence budget -> silently truncated mid-example,
                      so the assistant target may be cut off entirely
  contaminated        overlaps an eval question by text or by answer figure

Rejections are written out in full so the rejection rate can be audited rather than asserted.
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

from ..eval_match import matches_needle

REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_CHARS = 5200          # ~1300 tokens, under the 2048 seq budget with headroom
JACCARD_THRESHOLD = 0.60


def excerpt_body(e):
    """Excerpt text with the `[doc_id pN]` citation header removed.

    Several doc_ids contain digits (`oecd_economic_outlook_116_annex`,
    `census_poverty_2022_p60_280`), so matching a figure against the raw excerpt can match the
    CITATION LABEL rather than the document text. That both invented false ambiguity (a figure
    "116" appearing in every OECD header) and would have let an ungrounded figure pass as
    grounded. Grounding means present in the text, never in the label.
    """
    return re.sub(r"^\[[^\]]*\]\s*", "", e.strip())


def ngrams(text, n=5):
    toks = re.findall(r"[a-z0-9.]+", text.lower())
    return {tuple(toks[i:i + n]) for i in range(max(0, len(toks) - n + 1))}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def load_eval_questions():
    """All eval questions across every set, with the figures each requires."""
    out = []
    for f in ["gold_set.json", "holdout_set.json", "eval/multidoc_expanded.json"]:
        p = REPO_ROOT / f
        if not p.exists():
            continue
        for q in json.load(open(p)).get("questions", []):
            figs = {str(n) for n in (q.get("answer_contains") or [])}
            if q.get("expected_answer") is not None:
                figs.add(str(q["expected_answer"]))
            out.append({"set": f, "id": q.get("id"), "question": q["question"],
                        "grams": ngrams(q["question"]), "figures": figs})
    return out


def check(ex, evalqs):
    """Returns list of (code, detail). Empty means the example passes."""
    fails = []
    user = ex["messages"][1]["content"]
    ans = ex["messages"][2]["content"]
    meta = ex["meta"]
    context = user.split("\n\nQuestion:")[0]
    question = meta["question"]

    if len(user) > MAX_CHARS:
        fails.append(("too_long", f"{len(user)} chars > {MAX_CHARS}"))

    if "the reported figure" in question:
        fails.append(("degenerate_topic", "topic extraction produced a placeholder"))

    excerpts = [excerpt_body(e) for e in
                re.split(r"\n\n(?=\[)", context.replace("Excerpts:\n\n", "", 1))]
    body = "\n\n".join(excerpts)   # citation labels stripped: grounding is about text

    if meta["kind"] == "negative":
        if ans.strip() != "NOT_IN_CONTEXT":
            fails.append(("negative_bad_target", f"target was {ans[:40]!r}"))
        # A negative whose context DOES contain an asked-about figure would teach the model to
        # abstain when the answer is right there — a worse failure than the one being fixed.
        present = [f for f in meta.get("asked_figures", []) if matches_needle(body, f)]
        if present:
            fails.append(("negative_is_false", f"context contains asked figure(s) {present}"))
    else:
        fig = meta["figure"]
        if not matches_needle(body, fig):
            fails.append(("ungrounded_figure", f"answer figure {fig} not verbatim in context"))
        if not matches_needle(ans, fig):
            fails.append(("answer_lost_figure", f"{fig} missing from the answer text"))
        # The figure must appear in exactly ONE excerpt, else the supporting excerpt is ambiguous.
        hits = sum(1 for e in excerpts if matches_needle(e, fig))
        if hits > 1:
            fails.append(("ambiguous_figure", f"{fig} appears in {hits} excerpts"))
        # The half we claim is absent must actually be absent.
        other_doc = [d for d in meta["pair"].split("|") if d != meta["context_doc"]]
        if other_doc and other_doc[0] in body:
            fails.append(("leaked_other_half", f"context mentions {other_doc[0]}"))

    # Contamination, both directions, against every eval set.
    qg = ngrams(question)
    for e in evalqs:
        j = jaccard(qg, e["grams"])
        if j >= JACCARD_THRESHOLD:
            fails.append(("contaminated_text", f"jaccard {j:.2f} vs {e['set']}:{e['id']}"))
            break
    if meta.get("figure"):
        for e in evalqs:
            if meta["figure"] in e["figures"]:
                fails.append(("contaminated_figure",
                              f"figure {meta['figure']} is an answer in {e['set']}:{e['id']}"))
                break
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inp", default="data/train_multidoc.raw.jsonl")
    ap.add_argument("--out", default="data/train_multidoc.jsonl")
    ap.add_argument("--report", default="data/qc_report.md")
    args = ap.parse_args()

    raw = [json.loads(l) for l in open(REPO_ROOT / args.inp) if l.strip()]
    evalqs = load_eval_questions()
    print(f"checking {len(raw)} examples against {len(evalqs)} eval questions "
          f"from {len(set(e['set'] for e in evalqs))} sets")

    kept, rejected = [], []
    for ex in raw:
        fails = check(ex, evalqs)
        (kept if not fails else rejected).append(
            ex if not fails else {**ex, "_fails": fails})

    # Near-duplicate sweep within the kept set: prompts too similar teach nothing new.
    seen, deduped, dup_n = [], [], 0
    for ex in kept:
        g = ngrams(ex["meta"]["question"])
        if any(jaccard(g, s) >= 0.85 for s in seen):
            dup_n += 1
            rejected.append({**ex, "_fails": [("near_duplicate", "jaccard >=0.85 vs kept example")]})
            continue
        seen.append(g)
        deduped.append(ex)

    outp = REPO_ROOT / args.out
    with open(outp, "w") as fh:
        for ex in deduped:
            fh.write(json.dumps({"messages": ex["messages"]}) + "\n")
    with open(REPO_ROOT / "data" / "train_multidoc.meta.jsonl", "w") as fh:
        for ex in deduped:
            fh.write(json.dumps(ex["meta"]) + "\n")
    with open(REPO_ROOT / "data" / "qc_rejected.jsonl", "w") as fh:
        for ex in rejected:
            fh.write(json.dumps(ex) + "\n")

    reasons = Counter(c for ex in rejected for c, _ in ex["_fails"])
    rate = len(rejected) / len(raw) if raw else 0
    print(f"\nkept {len(deduped)}   rejected {len(rejected)}   rejection rate {rate:.1%}")
    for c, n in reasons.most_common():
        print(f"   {c:<22} {n}")

    lines = [
        "# Training data QC report", "",
        f"- input: `{args.inp}` — {len(raw)} raw examples",
        f"- output: `{args.out}` — **{len(deduped)} kept**",
        f"- rejected: **{len(rejected)}** — rejection rate **{rate:.1%}**",
        f"- near-duplicates removed in the dedup sweep: {dup_n}", "",
        "## Rejections by reason", "", "| reason | n |", "|---|---|",
    ]
    lines += [f"| `{c}` | {n} |" for c, n in reasons.most_common()]
    lines += ["", "## Contamination check", "",
              f"Checked against **{len(evalqs)} eval questions** across "
              f"{', '.join(sorted(set(e['set'] for e in evalqs)))}.", "",
              "Two independent methods, both directions:", "",
              "- **text** — token 5-gram Jaccard, threshold "
              f"{JACCARD_THRESHOLD}: {reasons.get('contaminated_text', 0)} hits",
              "- **answer figure** — the figure a training example teaches must never be the "
              f"answer to an eval question: {reasons.get('contaminated_figure', 0)} hits", "",
              "Figure-level exclusion is also applied *at construction time* in "
              "`gen_multidoc.py`, so this check is a verification of that guard rather than the "
              "only line of defence. The two agreeing is the point.", ""]
    (REPO_ROOT / args.report).write_text("\n".join(lines))
    print(f"wrote {args.report}")


if __name__ == "__main__":
    main()
