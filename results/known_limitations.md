# Known Limitations — durable record

Findings that must survive into `MEMO.md` (especially §2 quantization damage and §4 "what
verifies the verifier") and into the Phase 4 verification write-up. Parked here so they are not
lost between phases. Each entry states the mechanism, the evidence, and what it means for a
claim we might otherwise be tempted to make.

---

## L1 — The confidence score measures auditability, not correctness

**Status: open by design. Must be stated plainly in MEMO §4.**

`confidence = retrieval_score x path_factor x penalty` (see the DECISION note in
`src/qa/answer.py`). Every input is something we can observe about *how the answer was
produced* — how well the evidence matched the query, whether the path was code-computed or
LLM-summarised, whether the compute layer raised a unit warning. **None of them observe whether
the answer is right.**

**Evidence (a real case, not a hypothetical):** the question "What was the noncurrent loan rate
for construction and development loans at all insured institutions?" returned **0.38** at
**confidence 0.753**, with a valid citation to a real cell
(`fdic_quarterly_banking_profile_2024q1 p12 p12_t0 r4c1`) and a fluent rationale naming the
correct row and column. The true answer is **0.60**. The score was moderately high *because the
retrieval and compute machinery worked exactly as designed* — it just operated on a mislabelled
row (see L2).

**What this forbids us from claiming:** that confidence is calibrated, or that a high-confidence
answer is more likely correct. We have no calibration data supporting that, and one concrete
counterexample against it. Phase 4 should either (a) measure calibration honestly against the
gold set and report the curve, or (b) rename the field to something that does not imply
correctness. Do not quietly assert calibration.

---

## L2 — Label loss: values present, labels dropped (repaired, with residue)

pdfplumber's lines strategy dropped row labels and section banners on multi-block statistical
tables (FDIC Table V-A p12-13), leaving "vacant label" rows — a real value in col1 with an empty
col0. The values were in the store the whole time; nothing said what they were. Section banners
("Percent of Loans Noncurrent**") were dropped entirely, so blocks merged into their neighbours
and identical row labels ("Construction and development") became ambiguous across metrics.

Repaired by rebuilding affected tables from `page.extract_words()` clustered by `top` and
bucketed by the page's vertical rules (`src/ingest/tables.py`). **Residue is logged, not hidden:**
every row still carrying values without a label appears in `results/ingestion_check.md` as an
`INCOMPLETE:` breakage entry.

**Correction to the record:** this was first diagnosed as "an entire section was silently
dropped by extraction." That diagnosis was wrong — the data was present but unlabelled. See
`AI_LOG.md`.

**Post-fix state (measured, full corpus):** 38 tables showed the symptom, 11 were repaired,
**249 rows still hold values with no label**. Critically, **36 of the 260 retrievable tables
still carry unresolved label loss** — this is the fragile bucket that matters for gold-set
design, and it is not the same thing as the lines-vs-fallback split (198 / 62), which the repair
left unchanged. The repair is publisher-dependent: it works where pages have vertical rules
(FDIC 7/16, Fed MPR 2/2) and cannot work where they do not (BEA 0/5 — those pages carry no
vertical rules at all).

**Implication for Phase 3:** numeric gold questions should avoid the 36 tables listed as
`INCOMPLETE:` in `results/ingestion_check.md`, or verify the specific cell against the source
PDF first.

---

## L3 — Text-strategy fallback can split a number across columns — NOW DETECTED

The fallback that recovers borderless tables infers column boundaries from whitespace and
sometimes places a boundary *inside* a number: WASDE p12 `Area Planted` 2026/27 = **106.2** was
stored as two cells `10` and `6.2`; `95.4` became `9` and `5.4`. Adjacent rows in the same table
came through correctly.

**Detector** (`src/ingest/verify_cells.py`) — the same verify-store-against-source mechanism as
L2, aimed at this signature. Two signals:

- **split-number** (high precision, *suppressed from the answer path*): two horizontally adjacent
  cells whose digits concatenate into a number that appears on the source page, where the first
  cell's own value does not, **and** the decimal point falls in the second fragment and not the
  first — the observed cut-inside-the-integer-part signature. Corpus-wide: **8 split pairs
  (16 cells)** across WASDE (5) and the Census poverty report (3). Every one verified by eye.
- **orphan-number** (broad, noisy, *recorded only*): a purely numeric cell whose value appears
  nowhere on its source page as a standalone token. Too noisy to hide data on, so it is a
  diagnostic count, not a suppression rule.

**Two false-positive traps found and closed while building it** — both would have made the
detector actively misleading:

1. `float()` normalisation lost precision above 2^53, so concatenating two 9-digit FDIC cells
   produced an 18-digit value that rounded and collided with an unrelated page token. Every
   "split" flagged on FDIC — a lines-strategy document that cannot exhibit fallback splits —
   came from this. Fixed with exact string canonicalisation.
2. Without the decimal-position signature, short integers concatenate into other real page
   numbers by coincidence (`'93'+'5'` → `935`), **and** `extract_text()` merges adjacent wide
   columns the same way the table extractor does — so the check was validating an artefact
   against its own artefact. Adding the signature took the corpus from 294 flags (nearly all
   spurious) to 16.

**Suppression, not deletion:** flagged cells stay in `tables` (the raw store remains a faithful
record) but are withheld from `list_numeric_cells`, so the planner cannot compute on `10` when
the page says `106.2`.

**Related fix:** footnote/status markers (`106.2 *`, `1,234 r`, `56.7 p`) previously made a cell
fail the numeric test and be stored as text — so on WASDE p12 the *correct* value `106.2 *` sat
unusable beside the split fragments. `parse_cell` now strips trailing markers when the remainder
still parses as a number, recovering those values.

**Residual:** the detector only claims the signature it was built for. It does not detect splits
where the decimal lands in the first fragment, nor splits of pure integers. Gold-set cells drawn
from fallback tables still warrant an eyeball against source.

---

## L4 — Merged multi-number cells (fails safe)

16.2% of non-empty cells (8,527) hold two or more numbers merged into one cell (worst: OECD
annex 3,007; Treasury MTS 1,091; BEA GDP 1,037). These **fail safe**: `parse_cell` leaves them as
text, so `compute.fetch_cell` raises `ComputeError: cell is not numeric` rather than computing
something wrong. 53.9% (28,416 cells) are clean single numbers.

---

## L5 — Units usually live in headers, not cells

Only **147 of 34,759** numeric cells carry a unit, because units are typeset in column headers
(`Revenue ($M)`) rather than in the data cell. `parse_cell` deliberately does not infer units
from headers. This is expected to produce at least one genuine Phase 4 verification miss on a
unit-error claim — which is the honest outcome, not a bug to route around.

---

## L6 — The breakage log still cannot see all silent partial extraction

The log catches empty, ragged, raising, and (since L2) vacant-label tables. It does **not** catch
a table that returns plausible-but-incomplete data with intact labels. One instance was found and
fixed (a 1x3 fragment of a real 31x5 table on Fed MPR p65) only by manual inspection. The true
breakage count should be assumed higher than the number the report prints. Quantifying it needs
per-table ground truth we do not have.
