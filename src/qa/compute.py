"""Deterministic numeric compute over the structured table store.

CONSTRAINT #2 ENFORCEMENT LIVES HERE. The LLM never emits a final numeric answer — it emits a
*plan* (which table, which cells, which operation), and this module fetches those cells from
SQLite and does the arithmetic in Python. If the plan references a cell that doesn't exist or
isn't numeric, we fail loudly rather than letting a hallucinated number through.
"""
from dataclasses import dataclass, field
from typing import Optional

SUPPORTED_OPS = {"lookup", "sum", "diff", "ratio", "pct_change", "mean", "max", "min"}


class ComputeError(Exception):
    """Raised when a plan cannot be executed against the table store."""


@dataclass
class CellRef:
    doc_id: str
    table_id: str
    row: int
    col: int

    def as_citation(self, page=None, unit=None):
        return {
            "doc": self.doc_id, "page": page, "table_id": self.table_id,
            "cell": {"row": self.row, "col": self.col}, "unit": unit,
        }


@dataclass
class ComputeResult:
    value: float
    operation: str
    citations: list = field(default_factory=list)
    units: list = field(default_factory=list)
    unit_warning: Optional[str] = None

    @property
    def unit(self):
        distinct = {u for u in self.units if u}
        return distinct.pop() if len(distinct) == 1 else None


def fetch_cell(conn, ref: CellRef):
    """Returns (float_value, unit, page, header). Raises ComputeError if missing/non-numeric."""
    row = conn.execute(
        "SELECT value, unit, page, header FROM tables "
        "WHERE doc_id = ? AND table_id = ? AND row = ? AND col = ?",
        (ref.doc_id, ref.table_id, ref.row, ref.col),
    ).fetchone()

    if row is None:
        raise ComputeError(
            f"cell not found: {ref.doc_id}/{ref.table_id} r{ref.row}c{ref.col} — "
            f"the plan referenced a cell that does not exist in the table store"
        )

    value, unit, page, header = row
    if value is None:
        raise ComputeError(
            f"cell is blank: {ref.doc_id}/{ref.table_id} r{ref.row}c{ref.col}"
        )
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        raise ComputeError(
            f"cell is not numeric: {ref.doc_id}/{ref.table_id} r{ref.row}c{ref.col} "
            f"= {value!r} (header={header!r}) — refusing to compute over a text cell"
        )
    return numeric, unit, page, header


def execute_plan(conn, operation: str, cells: list) -> ComputeResult:
    """operation: one of SUPPORTED_OPS. cells: list of CellRef. All arithmetic happens here."""
    if operation not in SUPPORTED_OPS:
        raise ComputeError(f"unsupported operation {operation!r}; expected one of {sorted(SUPPORTED_OPS)}")
    if not cells:
        raise ComputeError(f"operation {operation!r} requires at least one cell reference")

    fetched = [fetch_cell(conn, ref) for ref in cells]
    values = [f[0] for f in fetched]
    units = [f[1] for f in fetched]
    citations = [ref.as_citation(page=f[2], unit=f[1]) for ref, f in zip(cells, fetched)]

    arity_2 = {"diff", "ratio", "pct_change"}
    if operation in arity_2 and len(values) != 2:
        raise ComputeError(f"operation {operation!r} requires exactly 2 cells, got {len(values)}")
    if operation == "lookup" and len(values) != 1:
        raise ComputeError(f"operation 'lookup' requires exactly 1 cell, got {len(values)}")

    if operation == "lookup":
        value = values[0]
    elif operation == "sum":
        value = sum(values)
    elif operation == "mean":
        value = sum(values) / len(values)
    elif operation == "max":
        value = max(values)
    elif operation == "min":
        value = min(values)
    elif operation == "diff":
        value = values[0] - values[1]
    elif operation == "ratio":
        if values[1] == 0:
            raise ComputeError("ratio undefined: denominator cell is 0")
        value = values[0] / values[1]
    elif operation == "pct_change":
        # (new - old) / old * 100, cells ordered [old, new]
        if values[0] == 0:
            raise ComputeError("pct_change undefined: baseline cell is 0")
        value = (values[1] - values[0]) / values[0] * 100.0

    # Unit-consistency guard: combining cells with genuinely different units is a real error,
    # not something to silently paper over. Recorded as a warning on the result so the caller
    # (and the verification layer) can see it rather than it vanishing.
    unit_warning = None
    distinct_units = {u for u in units if u}
    if operation in {"sum", "diff", "mean", "max", "min"} and len(distinct_units) > 1:
        unit_warning = (
            f"combined cells carry differing units {sorted(distinct_units)} — result may be "
            f"meaningless; units were NOT converted"
        )
    elif operation in {"sum", "diff", "mean"} and not distinct_units:
        unit_warning = (
            "no unit recorded on any source cell (units may live in the column header rather "
            "than the cell) — magnitude is unverified"
        )

    return ComputeResult(
        value=value, operation=operation, citations=citations,
        units=units, unit_warning=unit_warning,
    )
