"""Retrieval over the *structured* table store (kept separate from the prose index).

A table is retrieved by embedding a compact "preview" of it — the document title, its header
row, and its first-column row labels — rather than its numeric body. Numbers themselves make
terrible retrieval keys ("1,234" matches nothing a user would type); the labels around them are
what a question actually refers to.
"""
import json
from pathlib import Path

import faiss

from ..ingest.embed import get_model

TABLE_INDEX_DIR = Path(__file__).resolve().parents[2] / "index"
MAX_PREVIEW_ROWS = 12
MAX_PREVIEW_COLS = 8


def render_table_grid(conn, doc_id, table_id, max_rows=None, max_cols=None,
                      with_indices=True, value_only=False):
    """Render a stored table back into a text grid.

    with_indices=True prefixes row/col indices so the LLM can reference cells precisely —
    this is what makes a plan's {row, col} unambiguous and therefore checkable.
    """
    rows = conn.execute(
        "SELECT row, col, value, unit FROM tables WHERE doc_id = ? AND table_id = ? "
        "ORDER BY row, col",
        (doc_id, table_id),
    ).fetchall()
    if not rows:
        return ""

    max_r = max(r[0] for r in rows)
    max_c = max(r[1] for r in rows)
    if max_rows is not None:
        max_r = min(max_r, max_rows - 1)
    if max_cols is not None:
        max_c = min(max_c, max_cols - 1)

    grid = [["" for _ in range(max_c + 1)] for _ in range(max_r + 1)]
    for r, c, value, unit in rows:
        if r > max_r or c > max_c:
            continue
        cell = "" if value is None else str(value)
        if unit and not value_only:
            cell = f"{cell}{unit}" if unit == "%" else f"{cell} {unit}"
        grid[r][c] = cell

    lines = []
    if with_indices:
        lines.append("       " + " | ".join(f"c{c}" for c in range(max_c + 1)))
    for r_idx, row in enumerate(grid):
        prefix = f"r{r_idx:<4} " if with_indices else ""
        lines.append(prefix + " | ".join(row))
    return "\n".join(lines)


def build_table_previews(conn):
    """One preview string per table: doc title + header row + row labels."""
    previews = []
    tables = conn.execute(
        "SELECT DISTINCT doc_id, table_id, page FROM tables ORDER BY doc_id, page, table_id"
    ).fetchall()

    titles = dict(conn.execute("SELECT doc_id, title FROM documents").fetchall())

    for doc_id, table_id, page in tables:
        headers = conn.execute(
            "SELECT DISTINCT header FROM tables WHERE doc_id = ? AND table_id = ? "
            "AND header IS NOT NULL AND header != ''",
            (doc_id, table_id),
        ).fetchall()
        row_labels = conn.execute(
            "SELECT value FROM tables WHERE doc_id = ? AND table_id = ? AND col = 0 "
            "AND value IS NOT NULL ORDER BY row LIMIT ?",
            (doc_id, table_id, MAX_PREVIEW_ROWS),
        ).fetchall()

        header_text = " | ".join(h[0] for h in headers)
        label_text = " ; ".join(str(r[0]) for r in row_labels)
        title = titles.get(doc_id, doc_id)
        preview = f"{title} (page {page}). Columns: {header_text}. Rows: {label_text}"

        previews.append({
            "doc_id": doc_id, "table_id": table_id, "page": page, "preview": preview,
        })
    return previews


def build_table_index(conn, index_dir=TABLE_INDEX_DIR):
    previews = build_table_previews(conn)
    if not previews:
        return None, []
    model = get_model()
    embeddings = model.encode(
        [p["preview"] for p in previews], normalize_embeddings=True,
        convert_to_numpy=True, show_progress_bar=len(previews) > 200,
    ).astype("float32")

    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)

    index_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(index_dir / "tables.faiss"))
    with open(index_dir / "table_map.json", "w") as f:
        json.dump(previews, f)
    return index, previews


def load_table_index(index_dir=TABLE_INDEX_DIR):
    index = faiss.read_index(str(index_dir / "tables.faiss"))
    with open(index_dir / "table_map.json") as f:
        table_map = json.load(f)
    return index, table_map


def search_tables(query, index, table_map, top_k=5, doc_ids=None):
    model = get_model()
    q_emb = model.encode([query], normalize_embeddings=True, convert_to_numpy=True).astype("float32")
    # Over-fetch when filtering by doc so the filter doesn't starve the result set.
    fetch_k = top_k * 10 if doc_ids else top_k
    scores, indices = index.search(q_emb, min(fetch_k, len(table_map)))

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx == -1:
            continue
        entry = table_map[idx]
        if doc_ids and entry["doc_id"] not in doc_ids:
            continue
        results.append({**entry, "score": float(score)})
        if len(results) >= top_k:
            break
    return results
