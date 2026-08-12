"""Verify the stored table cells against the source page text.

Same mechanism as the label-loss completeness detector (constraint #5), aimed at a different
failure signature: the text-strategy fallback infers column boundaries from whitespace and can
place a boundary *inside a number*, storing WASDE's `106.2` as two cells `10` and `6.2 *`.

Two signals, both cheap and checkable against the PDF itself:

- **split-pair** (high precision): two horizontally adjacent cells whose digits, concatenated,
  form a number that DOES appear as a token on the source page, while the first cell's own value
  does NOT. Reconstructing to a real page value is strong evidence the boundary was misplaced.
- **orphan** (broader, noisier): a stored numeric cell whose value appears nowhere on its source
  page as a standalone numeric token. Every split fragment is an orphan, but so are some benign
  cases, so orphans are recorded and counted rather than used to suppress cells.

Flagged cells are written to `suspect_cells` and excluded from the numeric ANSWER path (see
`src/qa/table_index.py`). They are deliberately NOT deleted from `tables`: the raw store stays a
faithful record of what extraction produced, exactly as with the junk-table retrieval gate.
Suppressing a corrupt fragment at retrieval keeps a wrong number from being computed on;
deleting it would destroy the evidence that the defect happened.
"""
import re

import pdfplumber

NUMERIC_PREFIX = re.compile(r"-?\$?\(?-?[\d,]*\.?\d+\)?%?")
NUMERIC_FULL = re.compile(r"-?\$?\(?-?[\d,]*\.?\d+\)?%?")  # used with fullmatch()
TRUNCATED_DECIMAL = re.compile(r"-?\$?[\d,]+\.")           # "18." / "9." / "1,234." only

SUSPECT_SCHEMA = """
CREATE TABLE IF NOT EXISTS suspect_cells (
    doc_id   TEXT NOT NULL,
    page     INTEGER NOT NULL,
    table_id TEXT NOT NULL,
    row      INTEGER NOT NULL,
    col      INTEGER NOT NULL,
    reason   TEXT NOT NULL,
    detail   TEXT
);
CREATE INDEX IF NOT EXISTS idx_suspect ON suspect_cells(doc_id, table_id, row, col);
"""


def normalise_number(token):
    """Canonical numeric form, or None if the token does not start with a number.

    Canonicalisation is STRING-based on purpose. An earlier float() version silently produced
    false positives: concatenating two adjacent 9-digit FDIC cells gives an 18-digit value that
    exceeds float's exact-integer range, so `224647411220468213` rounded to `...224` and
    collided with an unrelated rounded page token. Every "split" flagged on FDIC — a
    lines-strategy document that should not exhibit fallback splits at all — came from that bug.
    Exact string comparison removes the whole class.
    """
    if token is None:
        return None
    match = NUMERIC_PREFIX.match(str(token).strip())
    if not match:
        return None
    text = match.group(0).rstrip("%").replace(",", "").lstrip("$")

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    if text.startswith("-"):
        negative, text = not negative, text[1:]
    if not text or not any(ch.isdigit() for ch in text):
        return None

    if "." in text:
        whole, _, frac = text.partition(".")
        frac = frac.rstrip("0")
    else:
        whole, frac = text, ""
    whole = whole.lstrip("0") or "0"

    canonical = f"{whole}.{frac}" if frac else whole
    if canonical == "0":
        return "0"
    return f"-{canonical}" if negative else canonical


def _digits(token):
    match = NUMERIC_PREFIX.match(str(token).strip())
    if not match:
        return None
    return match.group(0).replace(",", "").replace("$", "").rstrip("%")


def page_number_tokens(page):
    try:
        text = page.extract_text() or ""
    except Exception:
        return set()
    tokens = {normalise_number(t) for t in text.split()}
    tokens.discard(None)
    return tokens


def find_suspect_cells(conn, pdf_path, doc_id):
    """Returns list of (doc_id, page, table_id, row, col, reason, detail)."""
    suspects = []
    with pdfplumber.open(pdf_path) as pdf:
        pages_with_cells = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT page FROM tables WHERE doc_id = ? ORDER BY page", (doc_id,)
            )
        ]
        for page_num in pages_with_cells:
            if page_num - 1 >= len(pdf.pages):
                continue
            tokens = page_number_tokens(pdf.pages[page_num - 1])
            if not tokens:
                continue

            rows = conn.execute(
                "SELECT table_id, row, col, value FROM tables "
                "WHERE doc_id = ? AND page = ? AND value IS NOT NULL AND value != '' "
                "ORDER BY table_id, row, col",
                (doc_id, page_num),
            ).fetchall()

            grouped = {}
            for table_id, r, c, value in rows:
                grouped.setdefault((table_id, r), []).append((c, str(value)))

            split_flagged = set()
            for (table_id, r), cells in grouped.items():
                for i in range(len(cells) - 1):
                    (c1, v1), (c2, v2) = cells[i], cells[i + 1]
                    if c2 != c1 + 1:
                        continue
                    d1, d2 = _digits(v1), _digits(v2)
                    if not d1 or not d2:
                        continue
                    # Require the OBSERVED defect signature: the decimal point lands in the
                    # second fragment and not the first, i.e. a value like 106.2 was cut inside
                    # its integer part into "10" | "6.2".
                    #
                    # Without this the signal is worthless. Two adjacent short integers
                    # concatenate into some other number that happens to be on the page purely by
                    # chance ('93'+'5' -> 935), and — worse — pdfplumber's extract_text() merges
                    # adjacent wide columns exactly the way the table extractor does, so an
                    # 18-digit FDIC concatenation appears as a genuine "page token" and validates
                    # against its own artefact. Both sides of the comparison shared the defect.
                    # Restricting to this signature took the corpus from 294 flags (nearly all
                    # spurious) to 30.
                    #
                    # MIRROR SIGNATURE (added after it leaked into gold-set candidates): the cut
                    # can also land just after the decimal point, leaving a first fragment that
                    # ends in "." — Census poverty p15 stores 18.4 as `18.` | `4 Asian 3` and
                    # 9.8 as `9.` | `8 Non-Hispanic White`. A value ending in "." is malformed on
                    # its face, so this arm needs no page-token corroboration to be trustworthy;
                    # requiring it anyway would miss cases where the joined value never appears
                    # as a clean token because the fragment carries trailing label text.
                    if "." not in d2 or "." in d1:
                        continue
                    joined = normalise_number(d1 + d2)
                    if joined and joined in tokens and normalise_number(v1) not in tokens:
                        detail = f"{v1!r}+{v2!r} reconstructs to {joined} which is on the page"
                        for col in (c1, c2):
                            suspects.append(
                                (doc_id, page_num, table_id, r, col, "split-number", detail)
                            )
                            split_flagged.add((table_id, r, col))

            # MIRROR SIGNATURE, handled per-cell rather than per-pair. The cut can land just
            # after the decimal point, leaving a fragment that ends in "." — Census poverty p15
            # holds 18.4 as `18.` | `Asian 3` and 9.8 as `9.` | `8 Non-Hispanic White`.
            # Pair logic cannot catch these: the partner fragment often starts with label text
            # ("Asian 3") so it yields no digits at all, and `_digits` strips the trailing dot so
            # the first fragment stops looking malformed. Checking the raw stored value directly
            # sidesteps both problems — a value ending in "." is malformed on its face and needs
            # no page-token corroboration.
            for (table_id, r), cells in grouped.items():
                next_cell = {c: v for c, v in cells}
                for c, value in cells:
                    text = str(value).strip()
                    # Must be a bare number with a dangling decimal point and nothing else.
                    # A looser "ends with a dot" test fired 436 times corpus-wide, almost all
                    # of it prose ending in a full stop ("...refer to the BEA website.") and
                    # dot-leader runs ("42.7 49.7 45.0 ..............") — neither is a truncated
                    # value. Anchoring the whole cell brings it back to the real cases.
                    if not TRUNCATED_DECIMAL.fullmatch(text):
                        continue
                    # ...and the fragment that follows must actually begin with digits. Without
                    # this, ordered-list numbering matches perfectly: the OECD annex contents
                    # page stores "1." | "Demand and output for..." row after row, which is a
                    # list marker, not a cut number. 30 of the 124 flags were exactly that.
                    tail = str(next_cell.get(c + 1, "")).strip()
                    if not tail[:1].isdigit():
                        continue
                    if (table_id, r, c) in split_flagged:
                        continue
                    detail = (
                        f"{text!r} ends in a decimal point and the next cell {tail[:12]!r} "
                        f"begins with digits — value cut just after the decimal point"
                    )
                    for col in (c, c + 1):
                        suspects.append(
                            (doc_id, page_num, table_id, r, col, "split-number", detail)
                        )
                        split_flagged.add((table_id, r, col))

            for (table_id, r), cells in grouped.items():
                for c, value in cells:
                    if (table_id, r, c) in split_flagged:
                        continue
                    # Only flag cells that are PURELY numeric. A cell holding several merged
                    # numbers is already unusable and fails safe at compute time (L4), so
                    # flagging it here would add noise without adding protection.
                    if not NUMERIC_FULL.fullmatch(str(value).strip()):
                        continue
                    n = normalise_number(value)
                    if n is not None and n not in tokens:
                        suspects.append((
                            doc_id, page_num, table_id, r, c, "orphan-number",
                            f"value {n} does not appear as a numeric token on page {page_num}",
                        ))
    return suspects


def run(conn, corpus_dir, doc_ids=None):
    """Populate suspect_cells for the whole corpus. Returns per-doc counts."""
    conn.executescript(SUSPECT_SCHEMA)
    conn.execute("DELETE FROM suspect_cells")

    docs = conn.execute("SELECT doc_id, filename FROM documents ORDER BY doc_id").fetchall()
    counts = {}
    for doc_id, filename in docs:
        if doc_ids and doc_id not in doc_ids:
            continue
        pdf_path = corpus_dir / filename
        if not pdf_path.exists():
            continue
        suspects = find_suspect_cells(conn, pdf_path, doc_id)
        if suspects:
            conn.executemany(
                "INSERT INTO suspect_cells (doc_id, page, table_id, row, col, reason, detail) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                suspects,
            )
        conn.commit()
        counts[doc_id] = {
            "split": sum(1 for s in suspects if s[5] == "split-number"),
            "orphan": sum(1 for s in suspects if s[5] == "orphan-number"),
        }
    return counts
