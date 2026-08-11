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
import bisect

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


# ---------------------------------------------------------------------------
# Label-loss repair pass
# ---------------------------------------------------------------------------
# THE DEFECT THIS REPAIRS (found by chasing one wrong answer back to source):
# On FDIC Table V-A (p12-13) the lines strategy produced rows that alternate between a
# fully-populated labelled row and a "vacant label" row — col0 empty, but a real value sitting
# in col1. The vacant rows are not noise: they are the second half of a visually two-line row
# whose label pdfplumber dropped. Worse, the SECTION banners between metric blocks
# ("Percent of Loans Noncurrent**") were dropped entirely, so three of four blocks in that table
# merged into their neighbours.
#
# The visible consequence: asked for the noncurrent construction-and-development rate, the QA
# path returned 0.38 (the 30-89-day figure) instead of 0.60, cited to a real cell, at confidence
# 0.753. The number it needed was present in the store the whole time, at col1 of a vacant-label
# row, unreachable because nothing said what it was.
#
# HOW THE REPAIR WORKS: reconstruct the table from page.extract_words() — clustering words into
# rows by their `top` coordinate (ROW_CLUSTER_TOLERANCE) and bucketing them into columns by the
# page's own vertical rule x-positions. Deliberately NOT via find_tables()/cell objects, since
# those are the very structures that lost the labels.
#
# WHY IT IS A REPAIR AND NOT A REPLACEMENT: it only runs on tables that exhibit the vacant-label
# symptom. Tables that already carry complete labels are left exactly as the lines strategy
# produced them, so a fully-labelled table cannot regress. Anything the repair cannot resolve is
# logged to the breakage log rather than left to persist silently the way this defect did.
ROW_CLUSTER_TOLERANCE = 3.0   # pt; empirically tuned - see AI_LOG before/after diffs
MIN_VERTICAL_RULES = 2        # need at least 2 rules to define columns
MIN_VACANT_ROWS = 2           # below this, not worth suspecting systematic label loss


LABEL_COLS = (0, 1)      # some publishers put a line number in col0 and the label in col1
HEADER_ZONE_NUMERICS = 3  # first row with this many numerics ends the header zone


def _numeric_cols(cols):
    out = []
    for c, v in cols.items():
        if v is None or str(v).strip() == "":
            continue
        try:
            float(str(v).strip())
        except ValueError:
            continue
        out.append(c)
    return out


def _vacant_label_rows(table_rows):
    """Rows carrying data values that have no row label anywhere in the label columns.

    Precision matters more than recall here. An over-firing detector floods the breakage log
    with noise, and a log that cries wolf is its own kind of dishonesty — it makes the real
    entries unfindable. Two exclusions, both established empirically:

    - **Header-zone rows are skipped.** Multi-tier column headers legitimately have no row
      label (BEA GDP p10 rows 0-3 are stacked header tiers). The header zone ends at the first
      row carrying HEADER_ZONE_NUMERICS numeric values.
    - **The label may live in col0 OR col1.** BEA tables put a line number in col0 and the
      actual label in col1 ("43 | Net exports of goods and services"), so a col0-only test
      reported every BEA data row as label loss. Checking LABEL_COLS fixed that.

    Without these, the detector reported 284 "unlabelled" rows on a single BEA document, nearly
    all false positives.
    """
    by_row = {}
    for _d, _p, _t, r, c, value, _u, _h in table_rows:
        by_row.setdefault(r, {})[c] = value
    if not by_row:
        return []

    ordered = sorted(by_row)
    first_data = next(
        (r for r in ordered if len(_numeric_cols(by_row[r])) >= HEADER_ZONE_NUMERICS), None
    )
    if first_data is None:
        return []

    vacant = []
    for r in ordered:
        if r < first_data:
            continue
        cols = by_row[r]
        numeric_here = _numeric_cols(cols)
        if not numeric_here:
            continue
        has_label = False
        for lc in LABEL_COLS:
            v = cols.get(lc)
            if v is None or str(v).strip() == "":
                continue
            if lc not in numeric_here:   # a text cell in a label column = a label
                has_label = True
                break
        if not has_label:
            vacant.append(r)
    return sorted(vacant)


def _column_bounds(page):
    """Column boundaries from the page's own vertical rules (plus the rightmost edge)."""
    rules = sorted({round(l["x0"], 1) for l in page.lines if abs(l["x0"] - l["x1"]) < 0.6})
    if len(rules) < MIN_VERTICAL_RULES:
        return None
    right_edges = [round(e["x0"], 1) for e in page.edges if e.get("orientation") == "v"]
    right = max(right_edges) if right_edges else None
    if right is not None and right > rules[-1]:
        rules = rules + [right]
    return rules


def _cluster_words_into_rows(words, tolerance=ROW_CLUSTER_TOLERANCE):
    rows = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(w["top"] - rows[-1]["top"]) <= tolerance:
            rows[-1]["words"].append(w)
        else:
            rows.append({"top": w["top"], "words": [w]})
    return rows


def _repair_table_from_words(page, doc_id, page_num, table_id):
    """Rebuild one table from raw words + vertical rules. Returns cell_rows or None."""
    bounds = _column_bounds(page)
    if not bounds:
        return None
    try:
        words = page.extract_words(use_text_flow=False)
    except Exception:
        return None
    if not words:
        return None

    clustered = _cluster_words_into_rows(words)

    grid = []
    for entry in clustered:
        cols = {}
        for w in entry["words"]:
            centre = (w["x0"] + w["x1"]) / 2
            col = 0 if centre < bounds[0] else bisect.bisect_right(bounds, centre)
            cols.setdefault(col, []).append(w["text"])
        grid.append({c: " ".join(v) for c, v in cols.items()})

    # Header zone = rows before the first row carrying several numeric values. Their text is
    # concatenated per column to form that column's header, so multi-line stacked headers
    # ("All Insured" / "Institutions") survive as one label.
    def numeric_count(cols):
        n = 0
        for c, text in cols.items():
            if c == 0:
                continue
            value, _unit = parse_cell(text)
            if value is not None:
                try:
                    float(value)
                    n += 1
                except ValueError:
                    pass
        return n

    first_data = next((i for i, cols in enumerate(grid) if numeric_count(cols) >= 3), None)
    if first_data is None:
        return None

    headers = {}
    for cols in grid[:first_data]:
        for c, text in cols.items():
            headers[c] = f"{headers.get(c, '')} {text}".strip()

    cell_rows = []
    for r_idx, cols in enumerate(grid):
        for c_idx, text in sorted(cols.items()):
            value, unit = parse_cell(text)
            cell_rows.append((
                doc_id, page_num, table_id, r_idx, c_idx, value, unit,
                headers.get(c_idx, ""),
            ))
    return cell_rows or None


def extract_tables_from_pdf(pdf_path, doc_id):
    """Returns (cell_rows, breakages, stats).

    cell_rows: list of (doc_id, page, table_id, row, col, value, unit, header)
    breakages: list of {doc_id, page, table_id, reason} — logged, never silently dropped
               (constraint #5).
    stats:     counts for lines/fallback tables plus the label-loss repair pass.
    """
    cell_rows = []
    breakages = []
    stats = {
        "lines_tables": 0, "fallback_tables": 0, "fallback_pages": 0, "fallback_cells": 0,
        "vacant_label_tables": 0, "repaired_tables": 0, "repaired_rows_recovered": 0,
        "unresolved_vacant_rows": 0,
    }

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
                table_rows = []
                _store_table(table_rows, doc_id, page_num, table_id, raw_table, breakages, "lines")

                # Completeness check (constraint #5): a value with no label is unreachable data.
                vacant = _vacant_label_rows(table_rows)
                if len(vacant) >= MIN_VACANT_ROWS:
                    stats["vacant_label_tables"] += 1
                    repaired = _repair_table_from_words(page, doc_id, page_num, table_id)
                    repaired_vacant = _vacant_label_rows(repaired) if repaired else None

                    if repaired and len(repaired_vacant) < len(vacant):
                        stats["repaired_tables"] += 1
                        stats["repaired_rows_recovered"] += len(vacant) - len(repaired_vacant)
                        breakages.append({
                            "doc_id": doc_id, "page": page_num, "table_id": table_id,
                            "reason": (
                                f"REPAIRED: {len(vacant)} vacant-label row(s) had values but no "
                                f"row label (lines strategy dropped the labels); rebuilt from "
                                f"page words + {len(_column_bounds(page) or [])} vertical rules, "
                                f"leaving {len(repaired_vacant)}"
                            ),
                        })
                        table_rows = repaired
                        if repaired_vacant:
                            stats["unresolved_vacant_rows"] += len(repaired_vacant)
                            breakages.append({
                                "doc_id": doc_id, "page": page_num, "table_id": table_id,
                                "reason": (
                                    f"INCOMPLETE: {len(repaired_vacant)} row(s) still carry "
                                    f"values with no label after repair (rows "
                                    f"{repaired_vacant[:8]}) — those values are present in the "
                                    f"store but not addressable by label"
                                ),
                            })
                    else:
                        stats["unresolved_vacant_rows"] += len(vacant)
                        why = ("no vertical rules on page to define columns"
                               if _column_bounds(page) is None else
                               "repair produced no improvement")
                        breakages.append({
                            "doc_id": doc_id, "page": page_num, "table_id": table_id,
                            "reason": (
                                f"INCOMPLETE: {len(vacant)} row(s) hold values with no row label "
                                f"(rows {vacant[:8]}) and repair did not resolve them ({why}) — "
                                f"those values are in the store but not addressable by label"
                            ),
                        })

                cell_rows.extend(table_rows)
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
