"""Best-effort numeric-cell parsing: splits a raw table cell into (value, unit).

Deliberately does NOT reach into the column header to infer a unit for a bare numeric
cell (e.g. header "Revenue ($M)" with data cell "1,234" stays unit=None here) — units are
only recorded when they appear literally inside the cell itself ($, %, parentheses-negative).
This is a known, intentional gap: it mirrors a real ingestion failure mode (a unit that lives
only in the header can silently get lost from the per-cell record), and is worth surfacing
honestly rather than papering over with header-inference heuristics whose failure modes we
can't unit test as easily. See results/ingestion_check.md for the running list of gaps found.
"""
import re

_BLANK_TOKENS = {"", "-", "—", "–", "n/a", "na", "none"}
_CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}


def parse_cell(raw):
    if raw is None:
        return None, None
    text = str(raw).strip()
    if text.lower() in _BLANK_TOKENS:
        return None, None

    working = text
    unit = None

    # Statistical tables append footnote/status markers to values ("106.2 *", "45.1 **",
    # "1,234 r" for revised, "56.7 p" for preliminary). Left attached, the cell fails the
    # numeric test and is stored as TEXT, so a perfectly good value becomes uncomputable —
    # WASDE p12 held the correct `106.2 *` right next to the split fragments `10` / `6.2 *`,
    # and none of the three was usable. Markers are stripped only from the END and only when
    # what remains still parses as a number, so a genuinely textual cell is untouched.
    marker = re.search(r"[\s]*(?:\*+|\*\*+|(?<=\d)\s+[a-z]{1,2})$", working)
    if marker and marker.start() > 0:
        candidate = working[:marker.start()].strip()
        if re.fullmatch(r"[+-]?[\d,]*\.?\d+%?\)?", candidate.lstrip("($€£¥")):
            working = candidate

    if working.endswith("%"):
        unit = "%"
        working = working[:-1].strip()

    for sym, code in _CURRENCY.items():
        if working.startswith(sym):
            unit = code if unit is None else unit
            working = working[len(sym):].strip()
            break

    negative = False
    if working.startswith("(") and working.endswith(")"):
        negative = True
        working = working[1:-1].strip()

    cleaned = working.replace(",", "")
    if not re.fullmatch(r"[+-]?\d*\.?\d+", cleaned):
        return text, None

    try:
        num = float(cleaned)
    except ValueError:
        return text, None

    if negative:
        num = -num

    value = str(int(num)) if num.is_integer() else str(num)
    return value, unit
