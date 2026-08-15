"""Structural validity checks for eval/multidoc_expanded.json.

Was an ad-hoc heredoc; promoted to a committed script because it has now gated a go/no-go
decision twice, and because it must be re-run whenever src/eval_match.py changes — the checks
consume the matcher, so a matcher change can silently change what they report.

    python -m src.eval_checks

CHECK 1  both-documents-required — every cross-document question must be UNanswerable from any
         single one of its cited documents. This is a dependency check on the question, not a
         re-read of it: it pulls the real source pages and asks whether one page alone carries
         every required figure. A question that fails is not multi-doc at all.
CHECK 2  ground truth — every required figure appears verbatim on its own cited source page.
CHECK 3  partner-leak — one document's page must not contain the OTHER document's figure, which
         would let the question be answered from one source by coincidence.

Source text is read from the extracted page text, never from the SQLite store: the store is the
artifact under test, so using it as its own answer key would bless extraction defects.
"""
import json
import sys
from collections import Counter
from pathlib import Path

from .eval_match import missing_needles, matches_needle

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL = REPO_ROOT / "eval" / "multidoc_expanded.json"
PAGES = REPO_ROOT / "index" / "page_text"


def page_text(doc, page):
    """Raw extracted page text. Falls back to the per-document dump if pages aren't split out."""
    p = PAGES / f"{doc}_p{page}.txt"
    if p.exists():
        return p.read_text(errors="ignore")
    import fitz
    pdf = REPO_ROOT / "corpus" / f"{doc}.pdf"
    if not pdf.exists():
        return ""
    with fitz.open(pdf) as d:
        if page - 1 >= len(d):
            return ""
        return d[page - 1].get_text()


def main():
    qs = json.load(open(EVAL))["questions"]
    xdoc = [q for q in qs
            if isinstance(q.get("expected_citation"), list)
            and len({c["doc"] for c in q["expected_citation"]}) >= 2]
    ctrl = [q for q in qs if q not in xdoc]

    # ---- CHECK 1: both documents required -------------------------------------------------
    single_answerable = []
    for q in xdoc:
        needles = q["answer_contains"]
        for c in q["expected_citation"]:
            txt = page_text(c["doc"], c["page"])
            if not missing_needles(txt, needles):       # one page has EVERY figure
                single_answerable.append((q["id"], c["doc"], c["page"]))
    print(f"CHECK 1 — both-documents-required")
    print(f"  X-DOC questions checked : {len(xdoc)}")
    print(f"  answerable from ONE doc : {len(single_answerable)}")
    for qid, d, p in single_answerable:
        print(f"      {qid}: fully answerable from {d} p{p}")
    print(f"  -> {'PASS' if not single_answerable else 'FAIL'}\n")

    # ---- CHECK 2: ground truth ------------------------------------------------------------
    bad_truth = []
    for q in qs:
        cits = q["expected_citation"]
        cits = cits if isinstance(cits, list) else [cits]
        blob = "\n".join(page_text(c["doc"], c["page"]) for c in cits)
        miss = missing_needles(blob, q["answer_contains"])
        if miss:
            bad_truth.append((q["id"], miss))
    print(f"CHECK 2 — ground truth")
    print(f"  questions verified   : {len(qs)}")
    print(f"  with missing figures : {len(bad_truth)}")
    for qid, miss in bad_truth:
        print(f"      {qid}: {miss} not found on cited pages")
    print(f"  -> {'PASS' if not bad_truth else 'FAIL'}\n")

    # ---- CHECK 3: partner-leak ------------------------------------------------------------
    leaks = []
    for q in xdoc:
        cits = q["expected_citation"]
        for i, c in enumerate(cits):
            txt = page_text(c["doc"], c["page"])
            others = [cits[j] for j in range(len(cits)) if j != i]
            for o in others:
                otxt = page_text(o["doc"], o["page"])
                for n in q["answer_contains"]:
                    # a figure that belongs to the OTHER page but also appears on this one
                    if matches_needle(txt, n) and matches_needle(otxt, n):
                        leaks.append((q["id"], n, c["doc"], o["doc"]))
    leaks = list({(a, b, c, d) for a, b, c, d in leaks})
    print(f"CHECK 3 — partner-leak")
    print(f"  partner leaks: {len(leaks)}")
    for qid, n, a, b in leaks:
        print(f"      {qid}: {n} appears in both {a} and {b}")
    print(f"  -> {'PASS' if not leaks else 'FAIL'}\n")

    ops = Counter(q.get("operation") for q in qs)
    print(f"COMPOSITION: {len(xdoc)} cross-document · {len(ctrl)} controls · {len(qs)} total")
    print(f"  operations: {dict(ops)}")
    print(f"  distinct documents used: "
          f"{len({c['doc'] for q in qs for c in (q['expected_citation'] if isinstance(q['expected_citation'],list) else [q['expected_citation']])})}")

    ok = not (single_answerable or bad_truth or leaks)
    print(f"\n{'ALL CHECKS PASS' if ok else 'CHECKS FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
