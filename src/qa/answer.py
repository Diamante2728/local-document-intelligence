"""The single QA entry point: answer(q) -> {answer, citations, path_taken, confidence}.

Three paths (prose / numeric / multi-doc). Numbers only ever come out of
`compute.execute_plan` — the prose path is not allowed to answer a numeric question, and the
numeric path returns a refusal rather than a guess when planning or computing fails.
"""
import sqlite3

from ..ingest.db import DB_PATH
from ..ingest.embed import load_index, search
from .compute import ComputeError, execute_plan
from .llm import generate_text
from .plan import make_plan
from .hybrid import rrf_fuse
from .router import route
from .table_index import load_table_index, search_tables

# DECISION: retrieval top-k
# Default: k=5 prose chunks, k=5 candidate tables. On an 8GB M1 the binding constraint is the
# prompt: each rendered table grid is large, and KV-cache grows with context. k=5 tables keeps
# the planning prompt near ~2-3k tokens, which stays responsive at INT4.
# Rejected alternative: k=10-20 with a cross-encoder reranker. Better recall, but roughly
# doubles prompt size and adds a second model to a memory budget that has ~4-5GB usable — and
# reranker latency would confound the Phase 5 latency comparison.
TOP_K_PROSE = 5
TOP_K_TABLES = 3  # measured: k=5 put the planning prompt near 50s/question on this M1; k=3
                  # keeps it usable across the 20-question gold set x 3-rung ladder in Phase 5.

# DECISION: confidence-score formula
# Confidence is a transparent product of factors we can actually observe, NOT a model
# self-report (asking a 7B model "how confident are you?" yields well-documented overconfidence
# and would be exactly the kind of unearned trust signal this project exists to avoid).
#
#   confidence = retrieval_score * path_factor * penalty
#
# - retrieval_score: cosine similarity of the best retrieved evidence (already in [0,1]).
# - path_factor: how mechanically checkable the path is. Numeric answers are computed in Python
#   from cited cells, so they are auditable end-to-end (1.0). Prose answers depend on the LLM
#   faithfully summarizing retrieved text, which we cannot verify mechanically (0.85).
# - penalty: multiplicative deductions for observed problems — a unit warning from the compute
#   layer, a low-agreement router decision, or a multi-doc answer where only one document
#   actually contributed evidence.
#
# Rejected alternative: token-level logprob of the generated answer. Cheap to get, but it scores
# fluency, not correctness, and it is not comparable across the quantization ladder (Phase 5)
# because quantization shifts the logprob distribution itself — it would look like a confidence
# change when nothing about the evidence changed.
PATH_FACTOR = {"numeric": 1.0, "multi-doc": 0.9, "prose": 0.85}

# Routing confidences at or below this are treated as a weak call, and the numeric path's answer
# is checked against the prose path before being returned. route_rules() emits 0.85 for a clear
# signal and 0.7 for "some numeric cue, no prose cue" — the latter is exactly the band where
# "what was the <X> rate" questions land, and where the answer may live in prose rather than a cell.
ROUTE_CONFIDENT = 0.7

# (A MULTIDOC_NUMERIC_MIN_CONF threshold lived here and was removed — measurement showed table
#  retrieval scores do not separate "answer is in a table" from "answer is in prose on the same
#  topic". See the rationale block in answer_multidoc().)

PROSE_SYSTEM = (
    "Answer the question using ONLY the provided excerpts. Quote or closely paraphrase them. "
    "If the excerpts do not contain the answer, reply exactly: NOT_IN_CONTEXT. "
    "Never state a numeric figure that does not appear verbatim in the excerpts. "
    "Keep the answer to 1-3 sentences."
)


_bm25 = None


def _get_bm25(conn):
    """BM25 index over prose chunks, built once per process (~1s over 3,861 chunks)."""
    global _bm25
    if _bm25 is None:
        from .hybrid import build_bm25
        _bm25 = build_bm25(conn)
    return _bm25


def get_conn(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = None
    return conn


def _fetch_chunk_text(conn, chunk_id):
    row = conn.execute("SELECT text FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
    return row[0] if row else ""


def answer_prose(question, conn, prose_index, prose_map, top_k=TOP_K_PROSE, doc_ids=None):
    # DECISION: hybrid retrieval (dense + BM25, fused with RRF)
    # Dense-only retrieval missed P07 entirely: the answer sits in FDIC p1 and the chunk is in
    # the store, but a 384-dim embedding of a long page does not preserve the tokens that pin
    # the fact down ("FDIC-insured", "64.2"). BM25 ranks that same chunk FIRST (score 36.5),
    # because rare exact terms are precisely what document-frequency weighting rewards.
    # Fusion is Reciprocal Rank Fusion — BM25 scores and cosine similarities are on
    # incomparable scales, and RRF only consumes rank order, so no cross-calibration is needed.
    # Rejected: score-normalised averaging (requires calibrating two different scales, and the
    # calibration would have to be fitted on the gold set).
    fetch = top_k * 10 if doc_ids else top_k * 3
    dense = search(question, prose_index, prose_map, top_k=fetch)
    lexical = []
    try:
        bm25 = _get_bm25(conn)
        lexical = bm25.search(question, top_k=fetch, doc_ids=doc_ids)
    except Exception:
        pass  # lexical is an enhancement; dense alone must still work

    if doc_ids:
        dense = [h for h in dense if h["doc_id"] in doc_ids]
    hits = rrf_fuse(dense, lexical, top_k=top_k) if lexical else dense[:top_k]
    if not hits:
        return {
            "answer": "No relevant passage was retrieved.", "citations": [],
            "path_taken": "prose", "confidence": 0.0,
            "notes": ["retrieval returned no chunks"],
        }

    excerpts, citations = [], []
    for h in hits:
        text = _fetch_chunk_text(conn, h["chunk_id"])
        excerpts.append(f'[{h["doc_id"]} p{h["page"]}] {text}')
        citations.append({"doc": h["doc_id"], "page": h["page"], "chunk_id": h["chunk_id"],
                          "score": round(h["score"], 4)})

    prompt = "Excerpts:\n\n" + "\n\n".join(excerpts) + f"\n\nQuestion: {question}"
    text, _ = generate_text(prompt, max_tokens=256, system=PROSE_SYSTEM)
    text = text.strip()

    notes = []
    if "NOT_IN_CONTEXT" in text:
        return {
            "answer": "Not answerable from the retrieved passages.",
            "citations": citations, "path_taken": "prose", "confidence": 0.0,
            "notes": ["model reported the retrieved context does not contain the answer"],
        }

    confidence = hits[0]["score"] * PATH_FACTOR["prose"]
    return {"answer": text, "citations": citations, "path_taken": "prose",
            "confidence": round(min(confidence, 1.0), 3), "notes": notes}


def answer_numeric(question, conn, table_index, table_map, top_k=TOP_K_TABLES, doc_ids=None,
                   path_label="numeric"):
    candidates = search_tables(question, table_index, table_map, top_k=top_k, doc_ids=doc_ids)
    if not candidates:
        return {"answer": "No candidate table was retrieved.", "citations": [],
                "path_taken": path_label, "confidence": 0.0,
                "notes": ["table retrieval returned nothing"]}

    plan, error, raw, _elapsed = make_plan(question, candidates, conn)
    if plan is None:
        # Refuse rather than fall back to a generated number — constraint #2.
        return {
            "answer": f"Unable to produce a checkable numeric plan ({error}).",
            "citations": [{"doc": c["doc_id"], "page": c["page"], "table_id": c["table_id"]}
                          for c in candidates],
            "path_taken": path_label, "confidence": 0.0,
            "notes": [f"planning failed: {error}", f"raw model output: {raw.strip()[:200]}"],
        }

    # Evidence gate BEFORE computing: does the cell the planner chose actually relate to the
    # question? Without this the path returns whatever it was handed — observed "2,022" (a year)
    # at confidence 0.726 for a poverty-rate question. Returning no value routes the caller to
    # the prose fallback, which is the honest outcome when the table evidence is not there.
    from .plan import cell_supports_question
    unsupported = [c for c in plan.get("chosen_cells", [])
                   if not cell_supports_question(question, c)[0]]
    if unsupported and len(unsupported) == len(plan.get("chosen_cells", [])):
        _ok, detail = cell_supports_question(question, unsupported[0])
        return {
            "answer": f"No table cell matching the question was found ({detail}).",
            "citations": [{"doc": plan["doc_id"], "page": plan.get("page"),
                           "table_id": plan["table_id"]}],
            "path_taken": path_label, "confidence": 0.0,
            "notes": [f"evidence gate rejected the planner's cell(s): {detail}",
                      f"planner had chosen: {plan.get('selected')}"],
        }

    try:
        result = execute_plan(conn, plan["operation"], plan["cells"])
    except ComputeError as e:
        return {
            "answer": f"Plan could not be executed against the table store ({e}).",
            "citations": [{"doc": plan["doc_id"], "table_id": plan["table_id"]}],
            "path_taken": path_label, "confidence": 0.0,
            "notes": [f"compute failed: {e}", f"planned operation: {plan['operation']}"],
        }

    notes = []
    penalty = 1.0
    if result.unit_warning:
        notes.append(result.unit_warning)
        penalty *= 0.7

    best_score = candidates[0]["score"]
    chosen = next((c for c in candidates
                   if (c["doc_id"], c["table_id"]) == (plan["doc_id"], plan["table_id"])), None)
    retrieval_score = chosen["score"] if chosen else best_score

    value = result.value
    rendered = f"{value:,.4g}" if isinstance(value, float) else str(value)
    if result.unit == "%":
        rendered = f"{rendered}%"
    elif result.unit:
        rendered = f"{rendered} {result.unit}"

    confidence = retrieval_score * PATH_FACTOR.get(path_label, 1.0) * penalty
    return {
        "answer": rendered,
        "value": value,
        "citations": result.citations,
        "path_taken": path_label,
        "confidence": round(min(max(confidence, 0.0), 1.0), 3),
        "operation": result.operation,
        "notes": notes + ([f"planner rationale: {plan['reasoning']}"] if plan.get("reasoning") else []),
    }


def answer_multidoc(question, conn, prose_index, prose_map, table_index, table_map):
    """Answer across >=2 documents, citing each source separately.

    Each document gets a numeric sub-answer first (still computed in Python, constraint #2). If a
    document yields no number, it gets a PROSE sub-answer confined to that document.

    The prose arm is not an embellishment — without it this path could not answer most multi-doc
    questions at all. It originally ran the numeric path only and demanded a number from both
    documents, so questions whose facts live in sentences ("what GDP growth rate does BEA report,
    and what target range does the Fed report holding") returned "Could not compute a comparable
    figure" every time: 0 of 4 on the gold set, none of them a quantization effect.
    """
    # Candidate documents from BOTH indices: a document that is relevant in prose may contribute
    # nothing to the table index, and picking candidates from tables alone hid exactly those.
    docs_seen = []
    for hit in search_tables(question, table_index, table_map, top_k=TOP_K_TABLES * 2):
        if hit["doc_id"] not in docs_seen:
            docs_seen.append(hit["doc_id"])
    for hit in search(question, prose_index, prose_map, top_k=TOP_K_PROSE * 2):
        if hit["doc_id"] not in docs_seen:
            docs_seen.append(hit["doc_id"])

    per_doc = []
    for doc_id in docs_seen[:2]:
        # PROSE FIRST, numeric as fallback — the opposite of the single-document paths.
        #
        # Two earlier designs failed here and the reason is worth keeping:
        #   1. numeric-only, prose on `value is None`  -> the prose arm was dead code, because
        #      the numeric path ALWAYS returns some number (observed: 9, 2,022, 159.2 pulled
        #      from topically-related but wrong tables).
        #   2. numeric first, prose when confidence < 0.55 -> also never fired. Measured table
        #      retrieval for these questions: M01 0.719, M03 0.789, M04 0.704 — indistinguishable
        #      from a genuine numeric lookup. Retrieval score measures TOPICAL RELEVANCE, not
        #      which representation holds the answer: an FDIC net-income question legitimately
        #      matches FDIC tables strongly even though the figure lives in the narrative. No
        #      threshold can separate those, so tuning one would just be fitting the gold set.
        #
        # The asymmetry that does work: the prose path can ADMIT FAILURE. It returns
        # NOT_IN_CONTEXT (confidence 0.0) when the retrieved passages do not contain the answer.
        # The numeric path has no equivalent signal — it always produces a value. So ask the arm
        # that can say "I don't know" first, and only fall through when it does.
        # Bonus: this is also cheaper — one LLM call per document when prose succeeds, not two.
        sub = answer_prose(question, conn, prose_index, prose_map, doc_ids={doc_id})
        mode = "prose"
        if sub.get("confidence", 0.0) <= 0.0:
            numeric_sub = answer_numeric(question, conn, table_index, table_map,
                                         doc_ids={doc_id}, path_label="multi-doc")
            if numeric_sub.get("value") is not None:
                sub, mode = numeric_sub, "numeric"
        per_doc.append({"doc_id": doc_id, "mode": mode, **sub})

    contributing = [p for p in per_doc
                    if p.get("value") is not None or p.get("confidence", 0) > 0]
    citations = [c for p in contributing for c in p["citations"]]
    notes = [f'{p["doc_id"]} ({p["mode"]}): {str(p["answer"])[:110]}' for p in per_doc]
    modes = "+".join(sorted({p["mode"] for p in contributing})) or "none"

    if not contributing:
        return {
            "answer": "No source document could answer this question.",
            "citations": citations, "path_taken": "multi-doc", "confidence": 0.0,
            "notes": notes + ["0 of the candidate documents produced an answer"],
        }

    if len(contributing) < 2:
        # Say plainly that only one source was used rather than implying a comparison happened.
        only = contributing[0]
        return {
            "answer": f'Only one source could be used ({only["doc_id"]}): {only["answer"]}',
            "citations": citations, "path_taken": f"multi-doc({modes}, single-source)",
            "confidence": round(only.get("confidence", 0.0) * 0.6, 3),
            "notes": notes + ["fewer than 2 documents contributed — this is NOT a comparison"],
        }

    a, b = contributing[0], contributing[1]
    result = {
        "answer": f'{a["doc_id"]}: {a["answer"]}  |  {b["doc_id"]}: {b["answer"]}',
        "citations": citations,
        "path_taken": f"multi-doc({modes})",
        "confidence": round(min(a.get("confidence", 0.0), b.get("confidence", 0.0)), 3),
        "notes": notes,
    }
    # A numeric difference is only meaningful when both sides are numbers.
    if a.get("value") is not None and b.get("value") is not None:
        delta = a["value"] - b["value"]
        result["value"] = delta
        result["answer"] += f" (difference {delta:,.4g})"
    return result


_resources = None


def load_resources():
    global _resources
    if _resources is None:
        conn = get_conn()
        prose_index, prose_map = load_index()
        table_index, table_map = load_table_index()
        _resources = (conn, prose_index, prose_map, table_index, table_map)
    return _resources


def answer(question, use_llm_router=True):
    conn, prose_index, prose_map, table_index, table_map = load_resources()
    routing = route(question, use_llm_fallback=use_llm_router)
    path = routing["path"]

    if path == "numeric":
        result = answer_numeric(question, conn, table_index, table_map)
        # The prose/numeric split is NOT fully determinable from the question text: "by how much
        # did GDP increase" has a numeric answer that lives in a sentence, not a cell. When the
        # numeric path cannot produce a value — no plan, no cell, non-numeric cell — fall back to
        # prose rather than surfacing a refusal for a question the corpus can actually answer.
        # This is a genuine recovery, not a way to hide the failure: the fallback is recorded in
        # notes and path_taken becomes "numeric->prose" so the transcript stays honest.
        # Two distinct triggers for consulting the prose path:
        #   (a) the numeric path produced no value at all, or
        #   (b) routing itself was a weak call (ROUTE_CONFIDENT or below). Case (b) matters
        #       because a numeric lookup can succeed and still be nonsense: asked for the
        #       homeownership rate — a figure that lives in prose — the numeric path confidently
        #       returned 0.35 from an unrelated cell at confidence 0.692. A value being produced
        #       is not evidence the right path was taken, so on an uncertain route we run both
        #       and keep whichever has the stronger evidence.
        weak_route = routing.get("confidence", 1.0) <= ROUTE_CONFIDENT
        if result.get("value") is None or weak_route:
            fallback = answer_prose(question, conn, prose_index, prose_map)
            numeric_conf = result.get("confidence", 0.0) if result.get("value") is not None else -1
            if fallback.get("confidence", 0) > max(numeric_conf, 0.0):
                reason = ("numeric path produced no value" if result.get("value") is None
                          else f"router was only {routing.get('confidence')} confident and the "
                               f"prose path scored higher ({fallback['confidence']} vs "
                               f"{result.get('confidence')})")
                fallback["path_taken"] = "numeric->prose"
                fallback.setdefault("notes", []).insert(
                    0, f"{reason}; answered on the prose path instead "
                       f"(numeric attempt: {str(result.get('answer'))[:60]})"
                )
                result = fallback
    elif path == "multi-doc":
        result = answer_multidoc(question, conn, prose_index, prose_map, table_index, table_map)
    else:
        result = answer_prose(question, conn, prose_index, prose_map)

    result["routing"] = routing
    # A low-confidence route shouldn't be laundered into a high-confidence answer.
    if routing["confidence"] < 0.5:
        result["confidence"] = round(result["confidence"] * 0.9, 3)
        result.setdefault("notes", []).append(
            f'router was uncertain ({routing["method"]}: {routing["reason"]})'
        )
    return result
