"""Phase 1 orchestrator: corpus/*.pdf -> SQLite (tables + chunks) + FAISS prose index.

Usage: python -m src.ingest.run_ingest
"""
import re
import sys
from pathlib import Path

from . import db
from .embed import build_index, save_index
from .prose import extract_prose_chunks
from .tables import extract_tables_from_pdf

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = REPO_ROOT / "corpus"
RESULTS_DIR = REPO_ROOT / "results"


def doc_id_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    return re.sub(r"[^a-z0-9_]+", "_", stem.lower()).strip("_")


def ingest_all():
    pdf_paths = sorted(CORPUS_DIR.glob("*.pdf"))
    if not pdf_paths:
        print(f"No PDFs found in {CORPUS_DIR} — run download_corpus.py first.", file=sys.stderr)
        return

    conn = db.get_connection()
    # Full rebuild: table/chunk inserts are additive, so a re-run without this would silently
    # double every cell. Rebuilding from corpus/ is cheap and keeps the store reproducible.
    conn.executescript("DELETE FROM tables; DELETE FROM chunks; DELETE FROM documents;")
    conn.commit()

    all_breakages = []
    all_chunk_rows = []
    doc_summaries = []

    for pdf_path in pdf_paths:
        doc_id = doc_id_from_filename(pdf_path.name)
        print(f"Ingesting {pdf_path.name} -> doc_id={doc_id}")

        table_rows, table_breaks, table_stats = extract_tables_from_pdf(pdf_path, doc_id)
        chunk_rows, chunk_breaks, num_pages = extract_prose_chunks(pdf_path, doc_id)

        db.upsert_document(conn, doc_id, pdf_path.name, title=pdf_path.stem,
                            source_url=None, num_pages=num_pages)
        if table_rows:
            db.insert_table_cells(conn, table_rows)
        if chunk_rows:
            db.insert_chunks(conn, chunk_rows)
        conn.commit()

        all_chunk_rows.extend(chunk_rows)
        all_breakages.extend(table_breaks)
        all_breakages.extend(chunk_breaks)

        n_tables = len({r[2] for r in table_rows})
        doc_summaries.append({
            "doc_id": doc_id, "filename": pdf_path.name, "num_pages": num_pages,
            "n_tables": n_tables, "n_table_cells": len(table_rows),
            "n_chunks": len(chunk_rows), "n_breakages": len(table_breaks) + len(chunk_breaks),
            "fallback_tables": table_stats["fallback_tables"],
            "fallback_cells": table_stats["fallback_cells"],
            "fallback_pages": table_stats["fallback_pages"],
            "vacant_label_tables": table_stats["vacant_label_tables"],
            "repaired_tables": table_stats["repaired_tables"],
            "unresolved_vacant_rows": table_stats["unresolved_vacant_rows"],
        })
        print(f"  {num_pages} pages, {n_tables} tables ({len(table_rows)} cells), "
              f"{len(chunk_rows)} prose chunks, {len(table_breaks) + len(chunk_breaks)} breakages"
              f" [text-fallback recovered {table_stats['fallback_tables']} tables /"
              f" {table_stats['fallback_cells']} cells on {table_stats['fallback_pages']} pages]"
              f" [label-repair: {table_stats['repaired_tables']}/"
              f"{table_stats['vacant_label_tables']} symptomatic tables repaired, "
              f"{table_stats['unresolved_vacant_rows']} rows still unlabelled]")

    print(f"Building embedding index over {len(all_chunk_rows)} prose chunks...")
    if all_chunk_rows:
        index, id_map = build_index(all_chunk_rows)
        save_index(index, id_map)
        print(f"  saved to {REPO_ROOT / 'index'}")
    else:
        print("  no prose chunks extracted — skipping index build")

    # Verify stored cells against the source page text BEFORE building the retrieval index,
    # so split-number fragments are already suppressed from the answer path.
    from . import verify_cells
    print("Verifying stored cells against source page text...")
    suspect_counts = verify_cells.run(conn, CORPUS_DIR)
    n_split = sum(c["split"] for c in suspect_counts.values())
    n_orphan = sum(c["orphan"] for c in suspect_counts.values())
    print(f"  {n_split} split-number cells (suppressed from answers), "
          f"{n_orphan} orphan-number cells (recorded only)")

    # Table retrieval index (kept separate from the prose index — see src/qa/table_index.py).
    # Imported lazily: src.qa imports from src.ingest, so a module-level import here would
    # create a cycle.
    from ..qa.table_index import build_table_index
    print("Building table retrieval index...")
    _, previews = build_table_index(conn)
    print(f"  indexed {len(previews)} tables")

    write_ingestion_check(conn, doc_summaries, all_breakages)
    conn.close()


def write_ingestion_check(conn, doc_summaries, breakages, n_samples=8):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = ["# Ingestion Check\n"]

    lines.append("## Per-document summary\n")
    lines.append(
        "`tables` / `cells` are totals; the `via text-fallback` columns show how much of that "
        "total was recovered by the text-strategy fallback rather than the default lines "
        "strategy (see the DECISION note in `src/ingest/tables.py`).\n"
    )
    lines.append("| doc_id | pages | tables | table cells | via text-fallback (tables/cells) | "
                 "label-repair (repaired/symptomatic) | rows still unlabelled | prose chunks | "
                 "breakage log entries |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for s in doc_summaries:
        lines.append(
            f"| {s['doc_id']} | {s['num_pages']} | {s['n_tables']} | {s['n_table_cells']} | "
            f"{s['fallback_tables']} / {s['fallback_cells']} | "
            f"{s['repaired_tables']} / {s['vacant_label_tables']} | "
            f"{s['unresolved_vacant_rows']} | {s['n_chunks']} | {s['n_breakages']} |"
        )

    totals = {
        k: sum(s[k] for s in doc_summaries)
        for k in ("num_pages", "n_tables", "n_table_cells", "n_chunks", "n_breakages",
                  "fallback_tables", "fallback_cells", "vacant_label_tables",
                  "repaired_tables", "unresolved_vacant_rows")
    }
    lines.append(
        f"\n**Corpus totals:** {len(doc_summaries)} documents, {totals['num_pages']} pages, "
        f"{totals['n_tables']} tables, {totals['n_table_cells']} table cells "
        f"({totals['fallback_tables']} tables / {totals['fallback_cells']} cells recovered by "
        f"text-strategy fallback), {totals['n_chunks']} prose chunks, "
        f"{totals['n_breakages']} breakage-log entries.\n"
    )
    lines.append(
        f"**Label-loss repair:** {totals['vacant_label_tables']} tables showed the vacant-label "
        f"symptom (values present, row label dropped); {totals['repaired_tables']} were rebuilt "
        f"from page words + vertical rules. **{totals['unresolved_vacant_rows']} rows still hold "
        f"values with no label** — those values are in the store but cannot be addressed by "
        f"label, and every one is itemised in the breakage log below as `INCOMPLETE:`.\n"
    )

    lines.append("\n## Sample tables (eyeball check: did numbers/units survive?)\n")
    cur = conn.execute(
        "SELECT DISTINCT doc_id, table_id FROM tables ORDER BY doc_id, table_id LIMIT ?",
        (n_samples,),
    )
    sample_tables = cur.fetchall()
    if not sample_tables:
        lines.append("_No tables were extracted from any document — see breakage log below._\n")
    for doc_id, table_id in sample_tables:
        lines.append(f"### {doc_id} / {table_id}\n")
        rows = conn.execute(
            "SELECT page, row, col, value, unit, header FROM tables "
            "WHERE doc_id = ? AND table_id = ? ORDER BY row, col",
            (doc_id, table_id),
        ).fetchall()
        page = rows[0][0] if rows else "?"
        lines.append(f"(page {page})\n")
        max_row = max((r[1] for r in rows), default=0)
        max_col = max((r[2] for r in rows), default=0)
        grid = [["" for _ in range(max_col + 1)] for _ in range(max_row + 1)]
        for _, r, c, value, unit, _header in rows:
            cell = value or ""
            if unit:
                cell = f"{cell} {unit}"
            grid[r][c] = cell
        lines.append("| " + " | ".join(grid[0]) + " |")
        lines.append("|" + "---|" * len(grid[0]))
        for r in grid[1:6]:
            lines.append("| " + " | ".join(r) + " |")
        lines.append("")

    lines.append("## Known limitations of THIS report (what the breakage log does not catch)\n")
    lines.append(
        "The breakage log below records tables that came back **empty**, **ragged**, or that "
        "**raised**. It does not catch *silent partial extraction* — a table that returns "
        "plausible-looking but incomplete data. That failure mode is real and was observed "
        "directly: on `fed_monetary_policy_report_2024_03` p65, the default lines strategy "
        "returned a 1x3 fragment (`['2023','2024','2025']`) of a genuine 31x5 table, losing 108 "
        "of 111 populated cells **without logging anything**, because a 1x3 table is neither "
        "empty nor ragged. That specific case is what motivated the text-strategy fallback, and "
        "it is now recovered — but the general class of silent partial extraction is NOT "
        "detected by this report, and the true breakage count should be assumed higher than the "
        "number below. Quantifying it properly needs per-table ground truth we do not have; the "
        "gold set (Phase 3) samples this indirectly by pulling expected values from real pages.\n"
    )
    lines.append(
        "Second known gap: units are only recorded when the unit symbol appears **inside the "
        "cell**. A column headed `Revenue ($M)` with a bare cell `1,234` stores `unit=NULL`. See "
        "the docstring in `src/ingest/parse_cell.py` — this is deliberate and is expected to "
        "produce at least one honest verification miss in Phase 4.\n"
    )

    lines.append("## Breakage log (every table/page that broke, and why)\n")
    lines.append(
        "Entries prefixed `RECOVERED:` are not failures — they record where the text-strategy "
        "fallback fired and successfully recovered a borderless table.\n"
    )
    if not breakages:
        lines.append("_None recorded._\n")
    else:
        lines.append("| doc_id | page | table_id | reason |")
        lines.append("|---|---|---|---|")
        for b in breakages:
            lines.append(
                f"| {b['doc_id']} | {b['page']} | {b.get('table_id', '')} | {b['reason']} |"
            )

    (RESULTS_DIR / "ingestion_check.md").write_text("\n".join(lines) + "\n")
    print(f"Wrote {RESULTS_DIR / 'ingestion_check.md'}")


if __name__ == "__main__":
    ingest_all()
