"""Question router: prose / numeric / multi-doc.

# DECISION: numeric-vs-prose routing method
# Default: rules-first, LLM-fallback. A cheap deterministic rule layer classifies the clear
# cases (numeric cue words like "how much/total/average/percent/change", comparison-across-
# sources cues like "compare/versus/both reports/across documents"); only genuinely ambiguous
# questions pay for an LLM call.
#
# Why: routing is a *control-flow* decision, and on an 8GB M1 every LLM call costs ~2-6s. Rules
# are auditable, free, deterministic across the quantization ladder (Phase 5) — which matters a
# lot: if the router itself were LLM-driven end-to-end, INT4-vs-INT8 accuracy differences would
# partly reflect routing noise rather than answer quality, muddying the very comparison the
# ladder exists to make. Keeping routing mostly deterministic isolates the variable under test.
#
# Rejected alternative: LLM-classifies-everything. Cleaner conceptually and handles phrasing the
# rules miss, but slower, non-deterministic, and it contaminates the Phase 5 measurement as above.
# Rejected alternative: embedding-similarity to labelled example questions. Needs a labelled set
# we don't have yet, and its failures are harder to explain in a memo than a visible regex.
"""
import re

NUMERIC_CUES = [
    r"\bhow much\b", r"\bhow many\b", r"\btotal\b", r"\bsum\b", r"\baverage\b", r"\bmean\b",
    r"\bpercent\b", r"\bpercentage\b", r"\bratio\b", r"\brate\b", r"\bchange\b", r"\bgrowth\b",
    r"\bincrease\b", r"\bdecrease\b", r"\bdifference\b", r"\bhigher\b", r"\blower\b",
    r"\bmaximum\b", r"\bminimum\b", r"\blargest\b", r"\bsmallest\b", r"\bvalue of\b",
    r"\bwhat was the .*\b(?:value|amount|level|figure|number|count|rate)\b",
    r"\$", r"\d",
]

MULTIDOC_CUES = [
    r"\bcompare\b", r"\bcomparison\b", r"\bversus\b", r"\bvs\.?\b", r"\bboth\b",
    r"\bacross (?:the )?(?:documents|reports|sources)\b", r"\bbetween the two\b",
    r"\beach (?:report|document|source)\b", r"\bconsistent with\b", r"\bagree\b",
    r"\bdiffer\b", r"\bdiscrepan\w+\b", r"\bcontradic\w+\b",
]

PROSE_CUES = [
    r"^\s*(?:what|who|why|how) (?:is|are|was|were|does|do|did)\b",
    r"\bdescribe\b", r"\bexplain\b", r"\bsummar\w+\b", r"\bdefine\b", r"\bdefinition\b",
    r"\baccording to\b", r"\bstate[sd]?\b", r"\breason\b", r"\bpurpose\b", r"\bmethodology\b",
]

ROUTER_SYSTEM = (
    "You classify questions for a document-QA system. Reply with exactly one word: "
    "prose, numeric, or multi-doc. "
    "'numeric' = the answer is a number that must be read or computed from a table. "
    "'multi-doc' = answering requires combining or comparing information from two or more "
    "different documents. "
    "'prose' = the answer is descriptive text from a single document. No explanation."
)


def _count_hits(patterns, text):
    return sum(1 for p in patterns if re.search(p, text, re.IGNORECASE))


def route_rules(question: str):
    """Returns (path, confidence, reason) or (None, 0.0, reason) if rules are inconclusive."""
    q = question.strip()
    multi = _count_hits(MULTIDOC_CUES, q)
    numeric = _count_hits(NUMERIC_CUES, q)
    prose = _count_hits(PROSE_CUES, q)

    if multi:
        return "multi-doc", 0.85, f"matched {multi} multi-doc cue(s)"
    if numeric >= 2 and numeric > prose:
        return "numeric", 0.85, f"matched {numeric} numeric cue(s), {prose} prose cue(s)"
    if numeric and not prose:
        return "numeric", 0.7, f"matched {numeric} numeric cue(s), no prose cue"
    if prose and not numeric:
        return "prose", 0.8, f"matched {prose} prose cue(s), no numeric cue"
    return None, 0.0, f"inconclusive (numeric={numeric}, prose={prose}, multi={multi})"


def route(question: str, use_llm_fallback: bool = True):
    """Returns {path, confidence, method, reason}."""
    path, conf, reason = route_rules(question)
    if path is not None:
        return {"path": path, "confidence": conf, "method": "rules", "reason": reason}

    if not use_llm_fallback:
        return {"path": "prose", "confidence": 0.3, "method": "rules-default",
                "reason": f"{reason}; defaulted to prose with LLM fallback disabled"}

    from .llm import generate_text
    text, _ = generate_text(question, max_tokens=8, system=ROUTER_SYSTEM)
    label = text.strip().lower()
    for candidate in ("multi-doc", "multi doc", "numeric", "prose"):
        if candidate in label:
            normalized = "multi-doc" if candidate.startswith("multi") else candidate
            return {"path": normalized, "confidence": 0.6, "method": "llm-fallback",
                    "reason": f"{reason}; LLM classified as {normalized!r}"}

    return {"path": "prose", "confidence": 0.3, "method": "llm-fallback-unparsed",
            "reason": f"{reason}; LLM returned unparseable {text.strip()[:40]!r}, defaulted to prose"}
