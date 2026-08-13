"""Retrieval over the *structured* table store (kept separate from the prose index).

A table is retrieved by embedding a compact "preview" of it — the document title, its header
row, and its first-column row labels — rather than its numeric body. Numbers themselves make
terrible retrieval keys ("1,234" matches nothing a user would type); the labels around them are
what a question actually refers to.
"""
import json
import re
import sqlite3
from pathlib import Path

import faiss

from ..ingest.embed import get_model

TABLE_INDEX_DIR = Path(__file__).resolve().parents[2] / "index"
MAX_PREVIEW_ROWS = 24        # was 12 — too few to reach past the first section of a stacked table
MAX_PREVIEW_COLS = 10
MAX_PREVIEW_SECTIONS = 8     # section banners are the most discriminative terms; keep them all
PREVIEW_HARVEST_CELLS = 400  # how deep to scan a table when harvesting label vocabulary
MAX_CELL_CHARS = 40          # keeps a rendered grid row on one line; see render_table_grid

# Page furniture that pdfplumber sweeps into header/label positions on statistical publications.
# Left in, it dilutes the preview embedding with terms shared by every table in the document —
# FDIC p12_t0's preview was carrying "QUARTERLY", "2024 VOLUME", "NUMBER 2" and the report title,
# none of which distinguishes it from any other page of the same report.
_FURNITURE_PATTERNS = re.compile(
    r"^(?:quarterly|volume|number\s*\d*|\d{4}\s+volume|table\s+[ivx]+-?[a-z]?\b.*|"
    r"[a-z]+\s+\d{1,2},\s+\d{4}|page\s*\d+|\d+)$",
    re.IGNORECASE,
)


def _is_page_furniture(text):
    t = " ".join(str(text).split())
    if len(t) < 3:
        return True
    return bool(_FURNITURE_PATTERNS.match(t))

# DECISION: which tables are eligible for numeric retrieval
# Only tables with >= MIN_TABLE_CELLS non-empty cells AND >= MIN_TABLE_NUMERICS cleanly-parsed
# numeric cells are put in the retrieval index.
#
# Why: pdfplumber's detector fires on any ruled or whitespace-aligned region, so the raw store
# holds a lot of things that are not data tables — page furniture, figure captions, cover-page
# layout blocks. Measured on this corpus: of 939 detected tables, **63.7% contain zero cleanly
# numeric cells** and 44.7% have fewer than 6 non-empty cells; only **27.7% (260 tables)** clear
# both bars. Leaving the other 72% in the retrieval index actively causes wrong answers — an
# observed failure had the planner pick a 2-cell junk table (one cell holding a whole
# newline-crammed column) for a corn-production question, then reference a column that did not
# exist, because that junk table out-scored the real WASDE table.
#
# Rejected alternative: index everything and let the planner sort it out. That is what produced
# the failure above — a 7B model shown a nonsense grid guesses coordinates rather than declining.
# Rejected alternative: filter at ingestion (don't store junk tables at all). Rejected because
# the ingestion store should stay a faithful record of what pdfplumber actually produced —
# breakage honesty (constraint #5) depends on not quietly deleting the evidence. Filtering at
# *retrieval* keeps the raw record intact while keeping junk out of the answer path.
MIN_TABLE_CELLS = 6
MIN_TABLE_NUMERICS = 4


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
        # Cells can contain embedded newlines (wrapped text, or a whole cover-page block that
        # pdfplumber called a "table"). Left raw, they break the one-row-per-line layout the
        # model counts r/c indices against — it then references a column that does not exist.
        # Collapse to a single line and cap length so the grid stays a real grid.
        cell = " ".join(cell.split())
        if len(cell) > MAX_CELL_CHARS:
            cell = cell[:MAX_CELL_CHARS - 1] + "…"
        if unit and not value_only:
            cell = f"{cell}{unit}" if unit == "%" else f"{cell} {unit}"
        grid[r][c] = cell

    # Drop entirely-blank rows and columns from the RENDERED view while keeping each surviving
    # row/col's TRUE index in its label. The text-strategy fallback produces very sparse grids
    # (whole empty spacer columns between data columns); shown raw, the planner kept selecting
    # blank coordinates — an observed failure ("cell is blank: .../p9_ft0 r15c4"). Hiding empty
    # lanes while preserving real indices keeps every plan directly checkable against the store.
    keep_rows = [r for r in range(max_r + 1) if any(grid[r][c] for c in range(max_c + 1))]
    keep_cols = [c for c in range(max_c + 1) if any(grid[r][c] for r in keep_rows)]
    if not keep_rows or not keep_cols:
        return ""

    lines = []
    if with_indices:
        lines.append("        " + " | ".join(f"c{c}" for c in keep_cols))
    for r in keep_rows:
        prefix = f"r{r:<4}  " if with_indices else ""
        lines.append(prefix + " | ".join(grid[r][c] for c in keep_cols))
    return "\n".join(lines)


def is_retrievable_table(conn, doc_id, table_id):
    """Quality gate for the retrieval index — see the DECISION note at the top of this module."""
    values = conn.execute(
        "SELECT value FROM tables WHERE doc_id = ? AND table_id = ? "
        "AND value IS NOT NULL AND value != ''",
        (doc_id, table_id),
    ).fetchall()
    if len(values) < MIN_TABLE_CELLS:
        return False
    numerics = 0
    for (v,) in values:
        try:
            float(str(v).strip())
        except ValueError:
            continue
        numerics += 1
        if numerics >= MIN_TABLE_NUMERICS:
            return True
    return False


def _is_number(v):
    try:
        float(str(v).strip())
        return True
    except (TypeError, ValueError):
        return False


def list_numeric_cells(conn, doc_id, table_id, limit=40, query=None):
    """Enumerate a table's numeric cells with the labels a human would use to find them.

    Returns list of {row, col, value, unit, header, row_label, section}.

    `section` matters and is not decoration. Statistical tables routinely stack several metric
    blocks under one detected table — FDIC Table V-A p12 carries "Percent of Loans 30-89 Days
    Past Due", "Percent of Loans Noncurrent" and "Percent of Loans Charged-Off" one after
    another, each repeating the SAME row labels ("Construction and development", ...). Without
    the section, a row label is ambiguous across metrics, and the planner will pick the first
    match. That produced a real, confidently-cited WRONG answer during Phase 2 testing: asked
    for the noncurrent rate, the system returned 0.38 (the 30-89-day rate) instead of 0.60,
    citing a genuine cell with a genuine-looking row label at confidence 0.753.
    A section header is detected as a row whose only populated cell is a non-numeric label.
    """
    rows = conn.execute(
        "SELECT row, col, value, unit, header FROM tables WHERE doc_id = ? AND table_id = ? "
        "AND value IS NOT NULL AND value != '' ORDER BY row, col",
        (doc_id, table_id),
    ).fetchall()

    # Cells the source-verification pass proved are fragments of a split number (see
    # src/ingest/verify_cells.py) are withheld from the ANSWER path — computing on "10" when
    # the page says 106.2 is exactly the confidently-wrong-number failure this project exists to
    # prevent. Only the high-precision `split-number` class is suppressed; the broader
    # `orphan-number` signal is recorded for diagnostics but is too noisy to hide data on.
    # The rows stay in `tables` either way: the raw store remains a faithful record.
    suppressed = set()
    try:
        suppressed = {
            (r, c) for r, c in conn.execute(
                "SELECT row, col FROM suspect_cells WHERE doc_id = ? AND table_id = ? "
                "AND reason = 'split-number'",
                (doc_id, table_id),
            )
        }
    except sqlite3.OperationalError:
        pass  # suspect_cells not built yet; fall back to unfiltered behaviour

    by_row = {}
    for r, c, value, unit, header in rows:
        by_row.setdefault(r, []).append((c, value, unit, header))

    # Row label = leftmost non-numeric text cell on the row. Section header = a row that has
    # exactly one populated, non-numeric cell (a banner spanning the block beneath it).
    row_labels, section_at = {}, {}
    for r, cells in by_row.items():
        text_cells = [(c, v) for c, v, _u, _h in cells if not _is_number(v)]
        if text_cells:
            row_labels[r] = " ".join(str(text_cells[0][1]).split())[:60]
        if len(cells) == 1 and text_cells:
            section_at[r] = row_labels[r]

    # Merge consecutive banner rows: a section title that wrapped onto two lines
    # ("Percent of Loans Charged-Off" / "(net, YTD)") otherwise registers as two sections,
    # and the second — a bare qualifier — becomes the section label for the rows beneath it.
    for r in sorted(section_at):
        prev = r - 1
        if prev in section_at:
            section_at[r] = f"{section_at[prev]} {section_at[r]}".strip()
            section_at.pop(prev, None)

    def section_for(r):
        prior = [k for k in section_at if k < r]
        return section_at[max(prior)] if prior else ""

    out = []
    for r, c, value, unit, header in rows:
        if not _is_number(value):
            continue
        if r in section_at:
            continue
        if (r, c) in suppressed:
            continue
        out.append({
            "row": r, "col": c, "value": str(value).strip(), "unit": unit,
            "header": " ".join(str(header or "").split())[:50],
            "row_label": row_labels.get(r, ""),
            "section": section_for(r),
        })

    if len(out) <= limit:
        return out

    # Relevance-rank BEFORE truncating. Taking the first N cells in row order silently hides
    # everything below the cap: on FDIC p13 the 40-cell cap stopped inside the first metric
    # block, so the "Percent of Loans Noncurrent" cells were never shown and the planner could
    # not have chosen the right answer however well it reasoned. It picked the closest visible
    # cell (0.44) instead of 0.60 — a truncation artefact presenting as a reasoning failure.
    if query:
        q_terms = {t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2}
        for cell in out:
            context = f'{cell["row_label"]} {cell["header"]} {cell["section"]}'.lower()
            c_terms = set(re.findall(r"[a-z0-9]+", context))
            cell["_score"] = len(q_terms & c_terms)
        ranked = sorted(out, key=lambda c: -c["_score"])[:limit]
        for cell in ranked:
            cell.pop("_score", None)
        return sorted(ranked, key=lambda c: (c["row"], c["col"]))
    return out[:limit]


def build_table_previews(conn):
    """One preview string per RETRIEVABLE table: doc title + header row + row labels."""
    previews = []
    skipped = 0
    tables = conn.execute(
        "SELECT DISTINCT doc_id, table_id, page FROM tables ORDER BY doc_id, page, table_id"
    ).fetchall()

    titles = dict(conn.execute("SELECT doc_id, title FROM documents").fetchall())

    for doc_id, table_id, page in tables:
        if not is_retrievable_table(conn, doc_id, table_id):
            skipped += 1
            continue
        # Build the preview from the SAME label derivation the planner sees, not from a raw
        # `col = 0 LIMIT 12` query.
        #
        # Why this changed: the old query took the first 12 rows in row order, which on a
        # multi-section table covers only the FIRST metric block. FDIC Table V-A (p12_t0) stacks
        # five blocks, so its preview contained "Percent of Loans 30-89 Days Past Due" but NOT
        # "Percent of Loans Noncurrent", "Loans Outstanding (in billions)" or "Memo: Other Real
        # Estate Owned". A question asking about loans *outstanding* therefore had no lexical
        # overlap with the one table that holds the answer, and lost retrieval to an unrelated
        # balance-sheet table. Three gold numeric questions (N04, N05, N08) failed this way —
        # the planner never saw the right table, so no amount of cell-selection logic could help.
        cells = list_numeric_cells(conn, doc_id, table_id, limit=PREVIEW_HARVEST_CELLS)
        sections, row_labels, headers = [], [], []
        for c in cells:
            for value, bucket, cap in (
                (c["section"], sections, MAX_PREVIEW_SECTIONS),
                (c["row_label"], row_labels, MAX_PREVIEW_ROWS),
                (c["header"], headers, MAX_PREVIEW_COLS),
            ):
                v = (value or "").strip()
                if v and v not in bucket and len(bucket) < cap and not _is_page_furniture(v):
                    bucket.append(v)

        title = titles.get(doc_id, doc_id)
        # Sections first: they are the most discriminative terms on a stacked table, and are
        # exactly what distinguishes "noncurrent rate" from "loans outstanding" on the same rows.
        preview = (
            f"{title} (page {page}). "
            f"Sections: {' ; '.join(sections)}. "
            f"Rows: {' ; '.join(row_labels)}. "
            f"Columns: {' | '.join(headers)}"
        )

        previews.append({
            "doc_id": doc_id, "table_id": table_id, "page": page, "preview": preview,
        })
    print(f"  table retrieval index: kept {len(previews)}, "
          f"skipped {skipped} as non-numeric/too-small")
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
