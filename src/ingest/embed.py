"""Embedding index over prose chunks (table cells are retrieved by structured query, not
embedding search — the vector index is prose-only, kept separate from the table store).

# DECISION: embedding model
# Default: BAAI/bge-small-en-v1.5 (~130MB, CPU/MPS, ~384-dim). Chosen over all-MiniLM-L6-v2
# (~90MB) for its stronger MTEB retrieval scores at a similar size/speed budget — retrieval
# quality directly gates numeric-cell citation accuracy downstream, so we spend the small
# extra size on it. Runs via sentence-transformers on PyTorch's MPS backend; this is not the
# banned heavy HF `transformers` LLM path (see STACK notes in the build spec).
# Rejected alternative: all-MiniLM-L6-v2 — faster and smaller, but weaker on longer technical
# passages, which is most of this corpus.
"""
import json
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"
INDEX_DIR = Path(__file__).resolve().parents[2] / "index"

_model = None


def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBED_MODEL_NAME)
    return _model


def build_index(chunk_rows):
    """chunk_rows: list of (doc_id, chunk_id, page, text). Returns (faiss_index, id_map)."""
    model = get_model()
    texts = [row[3] for row in chunk_rows]
    embeddings = model.encode(
        texts, normalize_embeddings=True, show_progress_bar=len(texts) > 200,
        convert_to_numpy=True,
    ).astype("float32")

    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)  # normalized vectors -> inner product == cosine sim
    index.add(embeddings)

    id_map = [
        {"chunk_id": row[1], "doc_id": row[0], "page": row[2]} for row in chunk_rows
    ]
    return index, id_map


def save_index(index, id_map, index_dir=INDEX_DIR):
    index_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(index_dir / "prose.faiss"))
    with open(index_dir / "id_map.json", "w") as f:
        json.dump(id_map, f)


def load_index(index_dir=INDEX_DIR):
    index = faiss.read_index(str(index_dir / "prose.faiss"))
    with open(index_dir / "id_map.json") as f:
        id_map = json.load(f)
    return index, id_map


def search(query, index, id_map, top_k=5):
    model = get_model()
    q_emb = model.encode([query], normalize_embeddings=True, convert_to_numpy=True).astype("float32")
    scores, indices = index.search(q_emb, top_k)
    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx == -1:
            continue
        meta = dict(id_map[idx])
        meta["score"] = float(score)
        results.append(meta)
    return results
