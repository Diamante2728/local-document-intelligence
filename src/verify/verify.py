"""Verification layer (deliverable 1C): claim -> verdict + citation + confidence.

Verdicts are three-valued and the distinction is enforced structurally, not by prompt wording:

  supported     evidence was located AND it agrees with the claim
  contradicted  evidence was located AND it disagrees with the claim
  unverifiable  no evidence bearing on the claim was located at all

`contradicted` and `unverifiable` are NOT interchangeable. Collapsing "I found nothing" into
"this is false" is the single most tempting shortcut here and it would make the whole layer
dishonest: a verifier that says "contradicted" whenever retrieval fails scores well against a
set of planted errors while actually measuring its own retrieval failures. The code therefore
decides the verdict from *whether evidence was found* first, and only then from whether the
evidence agrees.

Numeric claims are re-checked by pulling the cited cells out of SQLite and comparing in Python —
the LLM is never asked whether a number is right (constraint #2 applies to verification too).
"""
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..ingest.db import DB_PATH
from ..ingest.embed import load_index, search
from ..qa.llm import extract_json, generate_text
from ..qa.table_index import list_numeric_cells, load_table_index, search_tables

REPO_ROOT = Path(__file__).resolve().parents[2]

# DECISION: numeric agreement tolerance
# A claim's number must match the recomputed value within RELATIVE_TOL (or ABSOLUTE_TOL for
# values near zero) to count as agreeing. Published tables round, and a claim that says "0.60"
# against a stored "0.6" is the same fact. Set tight enough that the planted wrong-number error
# (0.85 vs 0.60, a 42% gap) is unambiguous.
RELATIVE_TOL = 0.005
ABSOLUTE_TOL = 0.005

TOP_K_EVIDENCE = 6
MIN_EVIDENCE_SCORE = 0.35  # below this, retrieval found nothing genuinely on-topic

CLAIM_SYSTEM = (
    "You check whether a claim is supported by the evidence excerpts provided. "
    "You never use outside knowledge — only the excerpts.\n\n"
    "Reply with ONLY a JSON object:\n"
    '{"agrees": true|false|null, "reason": "<one short sentence>", '
    '"quote": "<the exact sentence from the excerpts that decides it, or empty>"}\n\n'
    'Use true if the excerpts state the claim. '
    'Use false if the excerpts state something that conflicts with the claim '
    '(a different value, a different period, a different source, a different unit). '
    'Use null if the excerpts simply do not address the claim — do NOT use false for that. '
    'Pay attention to WHICH ORGANISATION or WHICH TIME PERIOD the excerpts attribute a fact to; '
    'a correct number attached to the wrong period or the wrong source means the claim conflicts.'
)


@dataclass
class Verdict:
    claim_id: str
    verdict: str
    confidence: float
    citations: list = field(default_factory=list)
    evidence: str = ""
    reason: str = ""
    recomputed: Optional[float] = None
    claimed_value: Optional[float] = None
    notes: list = field(default_factory=list)


NUM_RE = re.compile(r"-?\$?\d[\d,]*\.?\d*")


def extract_claim_numbers(text):
    out = []
    for m in NUM_RE.finditer(text):
        raw = m.group(0).replace("$", "").replace(",", "")
        try:
            out.append((float(raw), m.group(0)))
        except ValueError:
            continue
    return out


def numbers_agree(a, b):
    if a is None or b is None:
        return False
    if abs(a) < 1.0 and abs(b) < 1.0:
        return abs(a - b) <= ABSOLUTE_TOL
    denom = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / denom <= RELATIVE_TOL


def gather_evidence(claim, conn, prose_index, prose_map, table_index, table_map):
    """Returns (excerpts, citations, best_score, table_cells)."""
    hits = search(claim, prose_index, prose_map, top_k=TOP_K_EVIDENCE)
    excerpts, citations = [], []
    for h in hits:
        row = conn.execute("SELECT text FROM chunks WHERE chunk_id = ?", (h["chunk_id"],)).fetchone()
        if not row:
            continue
        excerpts.append(f'[{h["doc_id"]} p{h["page"]}] {row[0]}')
        citations.append({"doc": h["doc_id"], "page": h["page"], "score": round(h["score"], 4)})

    table_cells = []
    for cand in search_tables(claim, table_index, table_map, top_k=3):
        cells = list_numeric_cells(conn, cand["doc_id"], cand["table_id"], limit=40, query=claim)
        for c in cells:
            table_cells.append({**c, "doc_id": cand["doc_id"], "table_id": cand["table_id"],
                                "page": cand["page"]})

    best = hits[0]["score"] if hits else 0.0
    return excerpts, citations, best, table_cells


# DECISION: when is a numeric recompute allowed to decide a verdict?
# Only when the claim can be tied to a specific stored cell BOTH strongly and unambiguously.
#
# The first version required just 2 overlapping label terms and then compared the cell against
# the FIRST number in the claim. It produced 7 false "contradicted" verdicts out of 15 claims
# (precision 0.300): it matched claim 12 ("poverty rate in 2022 was 11.5 percent") against the
# year 2022, and matched claim 8's "net charge-off rate for credit card loans" to the 30-89-day
# credit-card cell (1.55) because "charge-off"/"Charged-Off" share no whole-word token.
#
# A verifier that answers "contradicted" whenever its own cell-matching misfires is not being
# strict, it is manufacturing errors — and against a set of planted errors that failure is
# invisible in recall and only shows up in precision. So the bar is now:
#   - >= MIN_MATCH_TERMS distinctive terms overlap (prefix-matched, so charge/charged agree)
#   - the winning cell beats the best cell from any OTHER row by MATCH_MARGIN
#   - the claim's number is compared against ALL numbers it contains, not just the first
# If any of those fail, we return nothing and fall through to text-based verification rather
# than guessing.
MIN_MATCH_TERMS = 3
MATCH_MARGIN = 1
STOPWORDS = {
    "the", "and", "for", "was", "were", "with", "from", "that", "this", "than", "percent",
    "billion", "million", "rate", "rates", "total", "loans", "all", "its", "has", "have",
    "according", "reports", "reported", "increased", "decreased", "stood", "carried",
}


def _terms(text):
    return {t for t in re.findall(r"[a-z]+", text.lower()) if len(t) > 3 and t not in STOPWORDS}


def _overlap(claim_terms, ctx_terms):
    """Prefix-tolerant overlap so 'charge-off' matches 'Charged-Off', 'outstanding' 'Outstanding'."""
    hits = 0
    for ct in claim_terms:
        for xt in ctx_terms:
            if ct == xt or ct.startswith(xt[:5]) or xt.startswith(ct[:5]):
                hits += 1
                break
    return hits


def recompute_numeric(claim, table_cells):
    """Returns (cell, claimed_numbers) or (None, None) when no confident match exists.

    Matching is on LABELS, never on the claimed number itself — matching on the number would
    make a wrong-number claim look supported by finding whatever cell happens to hold that
    wrong number somewhere in the corpus.
    """
    claim_terms = _terms(claim)
    if not claim_terms:
        return None, None

    scored = []
    for cell in table_cells:
        ctx = _terms(f'{cell["row_label"]} {cell["header"]} {cell["section"]}')
        scored.append((_overlap(claim_terms, ctx), cell))
    if not scored:
        return None, None

    scored.sort(key=lambda x: -x[0])
    best_score, best = scored[0]
    if best_score < MIN_MATCH_TERMS:
        return None, None

    # Unambiguity: the runner-up from a DIFFERENT row/section must be clearly weaker. Cells in
    # the same row are just other columns of the same fact and do not indicate ambiguity.
    for score, cell in scored[1:]:
        same_row = (cell["row_label"], cell["section"]) == (best["row_label"], best["section"])
        if not same_row:
            if best_score - score < MATCH_MARGIN:
                return None, None
            break

    numbers = [v for v, _raw in extract_claim_numbers(claim)]
    # A bare 4-digit year is a period marker, not the measured quantity. Drop those unless the
    # claim contains nothing else (claim 12 compared 11.5 against the year 2022 without this).
    non_year = [n for n in numbers if not (1900 <= n <= 2100 and float(n).is_integer())]
    return best, (non_year or numbers)


def verify_claim(claim_id, claim, conn, prose_index, prose_map, table_index, table_map):
    excerpts, citations, best_score, table_cells = gather_evidence(
        claim, conn, prose_index, prose_map, table_index, table_map
    )

    # --- Step 1: did we find anything on-topic at all? ---
    if not excerpts or best_score < MIN_EVIDENCE_SCORE:
        return Verdict(
            claim_id=claim_id, verdict="unverifiable", confidence=round(best_score, 3),
            citations=citations, reason="no evidence above the relevance threshold was retrieved",
            notes=[f"best retrieval score {best_score:.3f} < {MIN_EVIDENCE_SCORE}"],
        )

    notes = []
    cell, claimed_numbers = recompute_numeric(claim, table_cells)
    recomputed = None

    # --- Step 2: numeric recompute in Python, when the claim carries a number we can locate ---
    if cell is not None and claimed_numbers:
        try:
            recomputed = float(cell["value"])
        except (TypeError, ValueError):
            recomputed = None

    if recomputed is not None:
        # The claim agrees if ANY number it states matches the recomputed cell. A claim often
        # carries several figures ("$28.4 billion, or 79.5 percent, to $64.2 billion") and only
        # one of them corresponds to the cell we matched; requiring the first to match produced
        # false contradictions.
        agrees = any(numbers_agree(n, recomputed) for n in claimed_numbers)
        claimed = next((n for n in claimed_numbers if numbers_agree(n, recomputed)),
                       claimed_numbers[0])
        cite = {"doc": cell["doc_id"], "page": cell["page"], "table_id": cell["table_id"],
                "cell": {"row": cell["row"], "col": cell["col"]},
                "row_label": cell["row_label"], "section": cell["section"],
                "unit": cell["unit"]}
        notes.append(
            f'recomputed from {cell["doc_id"]} {cell["table_id"]} '
            f'r{cell["row"]}c{cell["col"]} = {recomputed} '
            f'(claim states {claimed_numbers})'
        )
        if not cell["unit"]:
            notes.append(
                "source cell carries NO unit (units live in the section banner) — this check "
                "compares magnitudes only and cannot detect a unit error"
            )
        return Verdict(
            claim_id=claim_id,
            verdict="supported" if agrees else "contradicted",
            confidence=0.9 if agrees else 0.85,
            citations=[cite] + citations[:2],
            recomputed=recomputed, claimed_value=claimed,
            reason=("recomputed value matches the claim" if agrees
                    else f"recomputed {recomputed} does not match claimed {claimed}"),
            notes=notes,
        )

    # --- Step 3: no recomputable number — ask the LLM about the retrieved text only ---
    prompt = "Evidence excerpts:\n\n" + "\n\n".join(excerpts[:5]) + f"\n\nClaim: {claim}"
    raw, _ = generate_text(prompt, max_tokens=220, system=CLAIM_SYSTEM)
    data = extract_json(raw) or {}
    agrees = data.get("agrees", None)
    reason = str(data.get("reason", ""))[:300]
    quote = str(data.get("quote", ""))[:300]

    if agrees is True:
        verdict, conf = "supported", min(0.85, best_score + 0.25)
    elif agrees is False:
        verdict, conf = "contradicted", min(0.8, best_score + 0.2)
    else:
        verdict, conf = "unverifiable", round(best_score, 3)
        notes.append("evidence was retrieved but does not address the claim")

    return Verdict(
        claim_id=claim_id, verdict=verdict, confidence=round(conf, 3),
        citations=citations[:3], evidence=quote, reason=reason, notes=notes,
    )


def load_claims(path=REPO_ROOT / "summary.md"):
    claims = {}
    for line in Path(path).read_text().splitlines():
        m = re.match(r"^(\d+)\.\s+(.*\S)\s*$", line.strip())
        if m:
            claims[m.group(1)] = m.group(2)
    return claims


def run_all():
    conn = sqlite3.connect(DB_PATH)
    prose_index, prose_map = load_index()
    table_index, table_map = load_table_index()
    claims = load_claims()
    results = []
    for cid, text in sorted(claims.items(), key=lambda x: int(x[0])):
        print(f"  verifying claim {cid}...", flush=True)
        results.append(verify_claim(cid, text, conn, prose_index, prose_map,
                                    table_index, table_map))
    return claims, results


if __name__ == "__main__":
    claims, results = run_all()
    for v in results:
        print(f"{v.claim_id:>3}  {v.verdict:<13} conf={v.confidence:<6} {v.reason[:70]}")
