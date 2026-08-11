"""Table extraction: pdfplumber page.extract_tables() -> structured rows for SQLite.

Never flattens a table into prose (constraint #4) — every cell keeps its own
(doc_id, page, table_id, row, col, value, unit, header).

# DECISION: table extraction strategy (lines-first, text-fallback)
# Default: pdfplumber's default "lines" strategy, which infers table structure from ruled
# borders. It is high-precision — when a table has drawn rules, this gets the grid right and
# almost never invents a table out of prose.
#
# The problem it has: many statistical publications typeset tables with *dot leaders* and
# whitespace alignment instead of ruling lines (e.g. "Change in real GDP1......  ±0.8  ±1.7").
# The lines strategy sees no borders and returns either nothing or a tiny fragment. This was
# found empirically, not assumed: on the Fed Monetary Policy Report p65, the lines strategy
# returned a 1x3 fragment (['2023','2024','2025']) of a real 31x5 table — 108 of 111 populated
# cells silently lost.
#
# So: when the lines strategy yields nothing usable on a page that still *looks* numeric, retry
# with the "text" strategy (structure inferred from whitespace alignment). The text strategy is
# NOT used as the primary because it happily carves ordinary prose into a "table"; it is gated
# behind both a trigger (lines found nothing) and a plausibility filter (min rows/cols + digit
# density) to keep those false positives out.
#
# Rejected alternative: text strategy everywhere. Recovers more, but floods the table store with
# prose-shaped pseudo-tables, which would poison table retrieval in Phase 2 and inflate the
# apparent table count in a way that flatters the ingestion numbers dishonestly.
# Rejected alternative: camelot. It handles ruled tables well but needs Ghostscript, a system
# dependency not present on this machine (no Homebrew) — and it does not solve the borderless
# case above, which is the actual failure mode observed here.
#
# COST OF THIS FALLBACK (measured, not assumed — do not read the recovery numbers without it):
# the text strategy infers column boundaries from whitespace gaps, and on tables whose columns
# are narrowly spaced it sometimes places a boundary *inside* a number. Observed on
# usda_wasde_2026_06 p12: "Area Planted ... 106.2" was split across two cells as "10" and
# "6.2 *", and "95.4" as "9" and "5.4". Adjacent rows in the same table ("Beginning Stocks"
# 47.9 / 42.3 / 57.2, "Production" 391.1 / 447.5 / 419.7) came through correctly.
# So the fallback trades one failure mode (whole tables silently lost) for a different, noisier
# one (some values split across columns). That is a net gain — a split value fails loudly at
# compute time as a wrong-magnitude or non-numeric cell, whereas a lost table produced no signal
# at all — but it is NOT clean recovery, and any cell used as gold-set ground truth must be
# eyeballed against the source PDF rather than trusted because it is in the store.
"""
import pdfplumber

from .parse_cell import parse_cell

TEXT_STRATEGY = {
    "vertical_strategy": "text",
    "horizontal_strategy": "text",
    "text_x_tolerance": 2,
    "text_y_tolerance": 2,
}

# Fallback plausibility thresholds — a text-strategy table must clear all of these to be stored.
MIN_FALLBACK_ROWS = 3
MIN_FALLBACK_COLS = 2
MIN_FALLBACK_DIGIT_RATIO = 0.30
MIN_PAGE_NUMERIC_TOKENS = 20


def _nonblank_cells(table):
    return [c for row in table for c in row if c and str(c).strip()]


def _is_plausible_numeric_table(table):
    """Guards the text-strategy fallback against carving prose into pseudo-tables."""
    if len(table) < MIN_FALLBACK_ROWS:
        return False
    if not table or len(table[0]) < MIN_FALLBACK_COLS:
        return False
    cells = _nonblank_cells(table)
    if len(cells) < MIN_FALLBACK_ROWS * MIN_FALLBACK_COLS:
        return False
    numeric_like = sum(1 for c in cells if any(ch.isdigit() for ch in str(c)))
    return (numeric_like / len(cells)) >= MIN_FALLBACK_DIGIT_RATIO


def _page_looks_numeric(page):
    try:
        text = page.extract_text() or ""
    except Exception:
        return False
    return sum(1 for tok in text.split() if any(ch.isdigit() for ch in tok)) >= MIN_PAGE_NUMERIC_TOKENS


def _store_table(cell_rows, doc_id, page_num, table_id, raw_table, breakages, extractor):
    header_labels = [(c or "").strip() for c in raw_table[0]]
    for r_idx, row in enumerate(raw_table):
        if len(row) != len(header_labels):
            breakages.append({
                "doc_id": doc_id, "page": page_num, "table_id": table_id,
                "reason": (
                    f"row {r_idx} has {len(row)} cells, header row has {len(header_labels)} — "
                    f"ragged table, likely a merged-cell artifact ({extractor} strategy)"
                ),
            })
        for c_idx, cell in enumerate(row):
            header_label = header_labels[c_idx] if c_idx < len(header_labels) else None
            value, unit = parse_cell(cell)
            cell_rows.append((
                doc_id, page_num, table_id, r_idx, c_idx, value, unit, header_label,
            ))


def extract_tables_from_pdf(pdf_path, doc_id):
    """Returns (cell_rows, breakages, stats).

    cell_rows: list of (doc_id, page, table_id, row, col, value, unit, header)
    breakages: list of {doc_id, page, table_id, reason} — logged, never silently dropped
               (constraint #5).
    stats:     {"lines_tables", "fallback_tables", "fallback_pages", "fallback_cells"}
    """
    cell_rows = []
    breakages = []
    stats = {"lines_tables": 0, "fallback_tables": 0, "fallback_pages": 0, "fallback_cells": 0}

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            try:
                raw_tables = page.extract_tables()
            except Exception as e:
                breakages.append({
                    "doc_id": doc_id, "page": page_num, "table_id": None,
                    "reason": f"page.extract_tables() raised {type(e).__name__}: {e}",
                })
                continue

            stored_on_page = 0
            for t_idx, raw_table in enumerate(raw_tables):
                table_id = f"p{page_num}_t{t_idx}"
                if not raw_table or not _nonblank_cells(raw_table):
                    breakages.append({
                        "doc_id": doc_id, "page": page_num, "table_id": table_id,
                        "reason": "extract_tables() returned an empty/all-blank table "
                                  "(lines strategy; usually a chart's axes/gridlines "
                                  "detected as a table)",
                    })
                    continue
                _store_table(cell_rows, doc_id, page_num, table_id, raw_table, breakages, "lines")
                stored_on_page += 1
                stats["lines_tables"] += 1

            if stored_on_page > 0 or not _page_looks_numeric(page):
                continue

            # Fallback: lines strategy found nothing usable, but the page reads as numeric.
            try:
                fallback_tables = page.extract_tables(TEXT_STRATEGY)
            except Exception as e:
                breakages.append({
                    "doc_id": doc_id, "page": page_num, "table_id": None,
                    "reason": f"text-strategy fallback raised {type(e).__name__}: {e}",
                })
                continue

            recovered = 0
            for t_idx, raw_table in enumerate(fallback_tables):
                if not _is_plausible_numeric_table(raw_table):
                    continue
                table_id = f"p{page_num}_ft{t_idx}"  # ft = text-strategy fallback table
                before = len(cell_rows)
                _store_table(cell_rows, doc_id, page_num, table_id, raw_table, breakages, "text")
                stats["fallback_cells"] += len(cell_rows) - before
                stats["fallback_tables"] += 1
                recovered += 1

            if recovered:
                stats["fallback_pages"] += 1
                breakages.append({
                    "doc_id": doc_id, "page": page_num, "table_id": None,
                    "reason": f"RECOVERED: lines strategy found no usable table; text-strategy "
                              f"fallback recovered {recovered} table(s) — borderless/dot-leader "
                              f"layout",
                })

    return cell_rows, breakages, stats
