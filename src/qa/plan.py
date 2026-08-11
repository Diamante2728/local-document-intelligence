"""Numeric planning: the LLM picks table + cells + operation. It never produces the number.

The prompt deliberately never asks for a result value, and `parse_plan` deliberately never
reads one even if the model volunteers it — the only path to a number is `compute.execute_plan`
running Python over SQLite cells (constraint #2).
"""
from .compute import SUPPORTED_OPS, CellRef
from .llm import extract_json, generate_text

# Candidates are labelled TABLE 1..N and the model returns that integer, NOT a raw id string.
# Empirically necessary: asked for raw ids, the 7B model returned the doc_id in the table_id
# field, which the allow-list guard correctly rejected — a correct refusal, but a pointless one.
# An integer label removes the whole class of id-transcription error.
PLAN_SYSTEM = (
    "You are a planning component in a document-QA system. You NEVER compute or state numeric "
    "answers — a separate Python function does all arithmetic. Your only job is to identify "
    "which table cells the answer depends on and which operation combines them.\n\n"
    "Reply with ONLY a JSON object, no prose, in exactly this form:\n"
    '{"table": <integer label of the chosen table>, "operation": "<op>", '
    '"cells": [{"row": <int>, "col": <int>}], "reasoning": "<one short sentence>"}\n\n'
    f"Valid operations: {', '.join(sorted(SUPPORTED_OPS))}.\n"
    "- lookup: exactly 1 cell (read a single value)\n"
    "- diff / ratio / pct_change: exactly 2 cells, ordered [first, second]. "
    "For pct_change the order is [old, new].\n"
    "- sum / mean / max / min: 2 or more cells\n\n"
    '"table" must be one of the integer labels shown (e.g. 1, 2, 3). '
    "Row and column indices are shown in the grid as r0, r1, ... and c0, c1, ... "
    "Use those exact indices. Pick the cell containing the DATA VALUE, never the row label or "
    "the column header."
)

PLAN_TEMPLATE = """Question: {question}

Candidate tables:

{tables}

Return the JSON plan identifying the cells needed to answer the question."""


def build_plan_prompt(question, candidates, conn, max_rows=20, max_cols=10):
    """Returns (prompt, labelled) where labelled maps integer label -> candidate."""
    from .table_index import render_table_grid

    blocks = []
    labelled = {}
    for cand in candidates:
        grid = render_table_grid(
            conn, cand["doc_id"], cand["table_id"], max_rows=max_rows, max_cols=max_cols,
        )
        if not grid.strip():
            continue
        label = len(labelled) + 1
        labelled[label] = cand
        blocks.append(
            f'=== TABLE {label} === (from {cand["doc_id"]}, page {cand["page"]})\n{grid}'
        )
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

    chosen = labelled[label]
    doc_id, table_id = chosen["doc_id"], chosen["table_id"]

    raw_cells = data.get("cells")
    if not isinstance(raw_cells, list) or not raw_cells:
        return None, "plan contained no cell references"

    cells = []
    for c in raw_cells:
        if not isinstance(c, dict):
            return None, f"malformed cell reference {c!r}"
        try:
            row, col = int(c["row"]), int(c["col"])
        except (KeyError, TypeError, ValueError):
            return None, f"cell reference missing integer row/col: {c!r}"
        cells.append(CellRef(doc_id=doc_id, table_id=table_id, row=row, col=col))

    return {
        "doc_id": doc_id, "table_id": table_id, "page": chosen.get("page"),
        "operation": operation, "cells": cells,
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
