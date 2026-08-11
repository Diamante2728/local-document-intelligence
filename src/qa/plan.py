"""Numeric planning: the LLM picks table + cells + operation. It never produces the number.

The prompt deliberately never asks for a result value, and `parse_plan` deliberately never
reads one even if the model volunteers it — the only path to a number is `compute.execute_plan`
running Python over SQLite cells (constraint #2).
"""
from .compute import SUPPORTED_OPS, CellRef
from .llm import extract_json, generate_text

# DECISION: how the planner addresses cells
# Default: the model selects from an ENUMERATED list of that table's numeric cells by integer
# id — `[7] 254.51  (row: "2025/26 (Est.)" | column: "Ending Stocks")` — rather than emitting a
# raw (row, col) coordinate pair.
#
# Why, empirically: asking a 7B model for coordinates against a rendered grid failed repeatedly
# and in a specific way — it kept naming cells that were blank or out of range
# ("cell is blank: .../p9_ft0 r15c4", "cell not found: .../p35_t1 r1c1"). Text-strategy fallback
# tables are sparse and irregular, so 2D coordinate arithmetic over them is exactly the kind of
# spatial bookkeeping small models are worst at. Enumerating the *populated numeric cells* and
# letting the model pick one by id turns a 2D reasoning problem into a selection problem, and
# makes an out-of-range pick structurally impossible rather than merely detectable.
#
# What this does NOT change: the model still never emits the number. It names a cell id; Python
# resolves that id to (doc, table, row, col), fetches the stored value, and does the arithmetic.
# Constraint #2 is untouched — arguably strengthened, since the model can now only ever point at
# a cell that genuinely exists and genuinely holds a number.
#
# Rejected alternative: keep raw coordinates and just tell the model harder not to pick blanks.
# Tried in effect (blank-lane suppression in render_table_grid); it reduced but did not eliminate
# the failure, because blank *intersections* of populated rows and columns still exist.
# Also retained from an earlier fix: candidate tables are labelled TABLE 1..N and selected by
# integer, after the model was observed returning a doc_id in the table_id field.
PLAN_SYSTEM = (
    "You are a planning component in a document-QA system. You NEVER compute or state numeric "
    "answers — a separate Python function does all arithmetic. Your only job is to pick which "
    "already-extracted table cells the answer depends on, and which operation combines them.\n\n"
    "Reply with ONLY a JSON object, no prose, in exactly this form:\n"
    '{"table": <table number>, "operation": "<op>", "cells": [<cell id>], '
    '"reasoning": "<one short sentence>"}\n\n'
    f"Valid operations: {', '.join(sorted(SUPPORTED_OPS))}.\n"
    "- lookup: exactly 1 cell id\n"
    "- diff / ratio / pct_change: exactly 2 cell ids, ordered [first, second]. "
    "For pct_change the order is [old, new].\n"
    "- sum / mean / max / min: 2 or more cell ids\n\n"
    "Each candidate table lists its available cells as:\n"
    '  [<cell id>] <value>  (row: "<row label>" | column: "<column header>" '
    '| section: "<section header>")\n'
    "Choose cell ids ONLY from the list shown for the table you select. "
    "Match the row label, column header AND section against what the question asks for. "
    "The SAME row label often repeats under several sections measuring different things — "
    "the section decides which metric a number is, so check it before choosing."
)

PLAN_TEMPLATE = """Question: {question}

Candidate tables:

{tables}

Return the JSON plan naming the table number and the cell id(s) needed."""


def build_plan_prompt(question, candidates, conn, max_cells=40):
    """Returns (prompt, labelled).

    labelled maps table label -> {"candidate": ..., "cells": {cell_id: cell_dict}}.
    """
    from .table_index import list_numeric_cells

    blocks = []
    labelled = {}
    for cand in candidates:
        cells = list_numeric_cells(
            conn, cand["doc_id"], cand["table_id"], limit=max_cells, query=question,
        )
        if not cells:
            continue
        label = len(labelled) + 1
        # cell_id is 1-based and scoped to this table; the map back to (row, col) stays in
        # Python so the model can never address a cell that does not exist.
        labelled[label] = {"candidate": cand, "cells": {i + 1: c for i, c in enumerate(cells)}}

        lines = [f'=== TABLE {label} === (from {cand["doc_id"]}, page {cand["page"]})']
        for i, c in enumerate(cells, start=1):
            unit = f" {c['unit']}" if c["unit"] else ""
            section = f' | section: "{c["section"]}"' if c.get("section") else ""
            lines.append(
                f'  [{i}] {c["value"]}{unit}  (row: "{c["row_label"]}" | '
                f'column: "{c["header"]}"{section})'
            )
        blocks.append("\n".join(lines))
    return PLAN_TEMPLATE.format(question=question, tables="\n\n".join(blocks)), labelled


def parse_plan(raw_response, labelled):
    """Returns (plan_dict, error_str). plan_dict has doc_id, table_id, operation, cells."""
    data = extract_json(raw_response)
    if not isinstance(data, dict):
        return None, f"model did not return parseable JSON (got {raw_response.strip()[:120]!r})"

    operation = str(data.get("operation", "")).strip().lower()
    if operation not in SUPPORTED_OPS:
        return None, f"plan named unsupported operation {operation!r}"

    raw_label = data.get("table")
    try:
        label = int(raw_label)
    except (TypeError, ValueError):
        return None, f"plan did not name a valid integer table label (got {raw_label!r})"

    if label not in labelled:
        # Still a real guard: the planner may only compute over tables it was actually shown.
        return None, (
            f"plan referenced TABLE {label}, which was not among the {len(labelled)} candidate "
            f"tables shown — refusing to compute over a table the planner invented"
        )

    entry = labelled[label]
    chosen, cell_lookup = entry["candidate"], entry["cells"]
    doc_id, table_id = chosen["doc_id"], chosen["table_id"]

    raw_cells = data.get("cells")
    if not isinstance(raw_cells, list) or not raw_cells:
        return None, "plan contained no cell references"

    cells, selected = [], []
    for c in raw_cells:
        # Accept a bare id; also tolerate {"id": n} / {"cell": n} shapes small models emit.
        if isinstance(c, dict):
            c = c.get("id", c.get("cell", c.get("cell_id")))
        try:
            cell_id = int(c)
        except (TypeError, ValueError):
            return None, f"cell reference was not an integer cell id: {c!r}"

        if cell_id not in cell_lookup:
            return None, (
                f"plan referenced cell id {cell_id}, which is not among the "
                f"{len(cell_lookup)} cells listed for TABLE {label} — refusing to compute "
                f"over a cell the planner invented"
            )
        info = cell_lookup[cell_id]
        cells.append(CellRef(doc_id=doc_id, table_id=table_id, row=info["row"], col=info["col"]))
        selected.append(
            f'[{cell_id}] {info["value"]} (row "{info["row_label"]}" / col "{info["header"]}")'
        )

    return {
        "doc_id": doc_id, "table_id": table_id, "page": chosen.get("page"),
        "operation": operation, "cells": cells, "selected": selected,
        "reasoning": str(data.get("reasoning", ""))[:300],
    }, None


def make_plan(question, candidates, conn, max_tokens=250):
    """Returns (plan, error, raw_response, elapsed)."""
    if not candidates:
        return None, "no candidate tables retrieved", "", 0.0
    prompt, labelled = build_plan_prompt(question, candidates, conn)
    if not labelled:
        return None, "no candidate table could be rendered as a grid", "", 0.0
    raw, elapsed = generate_text(prompt, max_tokens=max_tokens, system=PLAN_SYSTEM)
    plan, error = parse_plan(raw, labelled)
    return plan, error, raw, elapsed
