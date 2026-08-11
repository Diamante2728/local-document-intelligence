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

PROSE_SYSTEM = (
    "Answer the question using ONLY the provided excerpts. Quote or closely paraphrase them. "
    "If the excerpts do not contain the answer, reply exactly: NOT_IN_CONTEXT. "
    "Never state a numeric figure that does not appear verbatim in the excerpts. "
    "Keep the answer to 1-3 sentences."
)


def get_conn(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = None
    return conn


def _fetch_chunk_text(conn, chunk_id):
    row = conn.execute("SELECT text FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
    return row[0] if row else ""


def answer_prose(question, conn, prose_index, prose_map, top_k=TOP_K_PROSE):
    hits = search(question, prose_index, prose_map, top_k=top_k)
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
    """Answer across >=2 documents, citing each. Numeric sub-answers still go through compute."""
    table_hits = search_tables(question, table_index, table_map, top_k=TOP_K_TABLES * 2)
    docs_seen, per_doc = [], []
    for hit in table_hits:
        if hit["doc_id"] in docs_seen:
            continue
        docs_seen.append(hit["doc_id"])
        if len(docs_seen) > 2:
            break

    for doc_id in docs_seen[:2]:
        sub = answer_numeric(question, conn, table_index, table_map,
                             doc_ids={doc_id}, path_label="multi-doc")
        per_doc.append({"doc_id": doc_id, **sub})

    usable = [p for p in per_doc if p.get("value") is not None]
    citations = [c for p in per_doc for c in p["citations"]]
    notes = [f'{p["doc_id"]}: {p["answer"]}' for p in per_doc]

    if len(usable) < 2:
        return {
            "answer": "Could not compute a comparable figure from two documents.",
            "citations": citations, "path_taken": "multi-doc",
            "confidence": 0.0,
            "notes": notes + [f"only {len(usable)} of {len(per_doc)} documents yielded a value"],
        }

    a, b = usable[0], usable[1]
    delta = a["value"] - b["value"]
    rendered = (f'{a["doc_id"]}: {a["answer"]} vs {b["doc_id"]}: {b["answer"]} '
                f'(difference {delta:,.4g})')
    confidence = min(a["confidence"], b["confidence"])
    return {"answer": rendered, "value": delta, "citations": citations,
            "path_taken": "multi-doc", "confidence": round(confidence, 3), "notes": notes}


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
