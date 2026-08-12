"""Propose gold-set candidate cells that survive every quality gate we know about.

Writing gold questions straight off the store would bake in the very defects Phase 1 spent its
time finding. This filters to cells that are:

  - in a table that passes the retrieval quality gate (>=6 cells, >=4 numerics)
  - NOT flagged `split-number` by the source-verification pass (L3)
  - NOT in a table with unresolved vacant-label rows (L2 residue, `INCOMPLETE:` in the log)
  - carrying a non-empty row label AND section/header context, so the question can name the
    cell unambiguously in words
  - from a lines-strategy table by default, since text-fallback tables have fragmented labels

Everything it proposes still has to be eyeballed against the source PDF before it becomes
ground truth — the filters remove known-bad cells, they do not prove a cell is right.

Usage: python -m src.verify.candidates [doc_id]
"""
import json
import sqlite3
import sys
from pathlib import Path

from ..ingest.db import DB_PATH
from ..qa.table_index import list_numeric_cells

REPO_ROOT = Path(__file__).resolve().parents[2]
INDEX_DIR = REPO_ROOT / "index"


def incomplete_tables(conn):
    """Tables the ingestion report flagged as still holding unlabelled rows."""
    report = REPO_ROOT / "results" / "ingestion_check.md"
    flagged = set()
    if not report.exists():
        return flagged
    for line in report.read_text().splitlines():
        if not line.startswith("|") or "INCOMPLETE:" not in line:
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) >= 3:
            flagged.add((parts[0], parts[2]))
    return flagged


def candidate_cells(conn, doc_id=None, lines_only=True, min_label_len=4, limit_per_table=6):
    with open(INDEX_DIR / "table_map.json") as f:
        table_map = json.load(f)

    skip = incomplete_tables(conn)
    out = []
    for entry in table_map:
        d, t, page = entry["doc_id"], entry["table_id"], entry["page"]
        if doc_id and d != doc_id:
            continue
        if lines_only and "_ft" in t:
            continue
        if (d, t) in skip:
            continue

        kept = 0
        for cell in list_numeric_cells(conn, d, t, limit=400):
            if len(cell["row_label"]) < min_label_len:
                continue
            if not cell["header"] and not cell["section"]:
                continue
            out.append({
                "doc_id": d, "table_id": t, "page": page,
                "row": cell["row"], "col": cell["col"], "value": cell["value"],
                "unit": cell["unit"], "row_label": cell["row_label"],
                "header": cell["header"], "section": cell["section"],
            })
            kept += 1
            if kept >= limit_per_table:
                break
    return out


def main():
    doc_id = sys.argv[1] if len(sys.argv) > 1 else None
    conn = sqlite3.connect(DB_PATH)
    cands = candidate_cells(conn, doc_id=doc_id)
    by_doc = {}
    for c in cands:
        by_doc.setdefault(c["doc_id"], []).append(c)
    print(f"{len(cands)} candidate cells across {len(by_doc)} documents\n")
    for d, cells in sorted(by_doc.items()):
        print(f"--- {d} ({len(cells)}) ---")
        for c in cells[:4]:
            sec = f' | {c["section"]}' if c["section"] else ""
            print(f'  p{c["page"]} {c["table_id"]} r{c["row"]}c{c["col"]} = {c["value"]}'
                  f'{" " + c["unit"] if c["unit"] else ""}')
            print(f'      row="{c["row_label"]}" | col="{c["header"]}"{sec}')


if __name__ == "__main__":
    main()
