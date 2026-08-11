# AI Log

Running log of what the coding assistant (Claude Code) did each phase, and anything it got
wrong that the user corrected. Feeds the AI-disclosure section of `MEMO.md`.

## Phase 0 — Setup

- Environment check: confirmed hardware is a MacBook Air, Apple M1, 8GB unified memory —
  matches the build spec's locked hardware plan.
- Found the system default `python3` is 3.7.0 (`/Library/Frameworks/Python.framework/Versions/3.7`),
  too old for `mlx-lm` (needs 3.9+). Located Python 3.11.5 via an existing Anaconda install
  (`/Users/mangilipallinagaraj/anaconda3`). Created a dedicated conda env (`doc-intel`, py3.11)
  rather than using `base`, to keep dependencies isolated and reproducible.
- Homebrew is not installed on this machine. Not a blocker for Phase 0 (only needed later if
  `camelot`/Ghostscript fallback is required for stubborn tables) — flagged for awareness.
- Created repo skeleton, `requirements.txt`, `.gitignore`, `README.md` stub, this log.
- No git identity was configured on this machine (`user.name`/`user.email` unset). Asked the
  user rather than assuming; also clarified that SSH/GPG keys are unrelated to this (those
  matter for pushing/signing, not for local commit authorship) since the user asked about them.
  Set locally (`git config --local`, this repo only) per user's answer: Nagaraj Mangilipalli /
  nagarajmangilipalli@gmail.com.
- Installed `mlx-lm sentence-transformers faiss-cpu pdfplumber pymupdf pandas cryptography`
  into the `doc-intel` env. All imports verified clean. `mx.default_device()` → `Device(gpu, 0)`,
  confirming Metal is visible to MLX.
- Downloaded `mlx-community/Qwen2.5-7B-Instruct-4bit` (~4.0GB on disk, matches expected INT4
  footprint). Ran the offline proof with `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` rather than
  physically disabling the machine's Wi-Fi — chose not to take that action unilaterally on the
  user's machine; the env-var approach proves the same thing (no network call possible) and is
  reproducible in CI. Full transcript + interpretation in `results/phase0_offline_proof.md`.
- **Correction I made myself before reporting:** the first `generate()` call measured a
  misleadingly slow 0.39 tok/s. This is MLX's one-time Metal shader JIT-compilation cost on
  first use, not real throughput — caught it by re-running warm calls in the same process
  before reporting a baseline, rather than reporting the cold number at face value. Warm
  steady-state baseline: **~9 tok/s** at INT4, batch size 1.
- Noted system-wide swap was already at 9.2GB used before this session's model run — flagged as
  a pre-existing condition (other background apps), not something Phase 0's test caused, and as
  a reminder that Phase 5 swap measurements need a clean baseline.
- **Foundation check passed:** model loads and generates offline within budget (peak MLX memory
  4.41GB, well under the ~4-5GB usable budget on this 8GB machine). Proceeding to Phase 1.

## Phase 1 — Ingestion (in progress)

- Wrote SQLite schema (`src/ingest/db.py`) exactly matching the spec's `tables(doc_id, page,
  table_id, row, col, value, unit, header)`, plus a `documents` and `chunks` table.
- `# DECISION` (chunking size/strategy): per-page, paragraph-aware chunking, 800-char cap,
  100-char overlap on over-long paragraphs, chunks never span pages. Rejected: whole-document
  fixed-size sliding window (the common RAG default) — rejected because it breaks per-page
  citation precision (constraint #3), which this project treats as non-negotiable. Documented
  in `src/ingest/prose.py`.
- `# DECISION` (embedding model): `BAAI/bge-small-en-v1.5` over `all-MiniLM-L6-v2` — stronger
  MTEB retrieval scores at similar size/speed cost, and retrieval quality gates citation
  accuracy downstream. Documented in `src/ingest/embed.py`.
- Cell-level unit parsing (`src/ingest/parse_cell.py`) is deliberately **not** header-inferring:
  it only records a unit when the symbol/sign appears literally in the cell (`$`, `%`,
  parentheses-negative). A header like `Revenue ($M)` next to a bare cell `1,234` yields
  `unit=None` on the cell. This is an intentional, documented gap, not an oversight — it's the
  exact mechanism the build spec's Phase 4 "honest miss" example describes, and forcing it
  artificially would be dishonest; better to let a real ingestion design choice produce it.
- **Self-caught bug:** first draft of `prose.py` had an unclosed module docstring (the
  `# DECISION` comment block was written as unterminated `"""..."""`), which silently absorbed
  the rest of the file into the string until Python hit EOF — caught immediately by running the
  smoke test below rather than assuming the file was fine because it "looked done."
- **Smoke test** (synthetic PDF, not part of the real corpus — built with PyMuPDF's own drawing
  API to avoid depending on a table library that doesn't exist here): table extraction correctly
  parsed `1,234`→`1234` (unit=None, the documented gap above), `(120)`→`-120`
  (parentheses-negative), `5.2%`→`5.2`+unit `%`. Embedding index build+search also verified: a
  query about revenue growth correctly ranked the revenue chunk (score 0.67) above an unrelated
  climate chunk (score 0.53).
- **Real-corpus observation from the smoke test:** PyMuPDF's `get_text("text")` on a page that
  also contains a table picks up the table's cell text as part of the page's prose stream (since
  it's just laid-out text to PyMuPDF, not aware pdfplumber separately parsed it as a table). This
  means prose chunks from table-bearing pages will contain duplicated/fragmented table content
  alongside real prose. Not fixed in Phase 1 — flagging for Phase 2, where the router may need to
  down-weight or filter prose-path retrieval results that are mostly numeric/table-shaped text,
  since the numeric path should be answering those questions via the structured table store, not
  a prose chunk.
- `download_corpus.py` written with retry/backoff download mechanics and a PDF-content-type
  verification check. Corpus URLs were **verified by actual HTTP fetch + PDF-parse** rather than
  guessed: 16 documents from FDIC, BEA (x3), Census (x3), Federal Reserve (x2), USDA (x2), OECD,
  Treasury, World Bank, EPA, EIA. All 16 downloaded successfully from this machine (39MB, 713
  pages). Sources that returned HTTP 403 to the research pass (BLS, SSA, CBO, IMF) were **not**
  included rather than guessed at — noted as retryable from a residential network if more docs
  are wanted later.
- Reproducibility caveat recorded in `download_corpus.py`: 15 of 16 URLs are dated/archive
  links (fixed snapshots); `census_housing_vacancies` is only published at a rolling URL whose
  contents change quarterly. Flagged in-file rather than silently accepted.

### The significant Phase 1 finding: silent partial table extraction

- First ingestion run completed: 74,859 table cells, 3,865 prose chunks, 195 breakage entries.
  But two documents looked wrong on inspection — `fed_monetary_policy_report_2024_03` yielded
  only **5 tables / 131 cells from 71 pages**, and `usda_wasde_2026_06` only **4 tables / 329
  cells from 40 pages**. Both are famously table-dense publications, so I treated those numbers
  as a symptom rather than a result.
- Diagnosis (done by inspecting the actual PDFs, not by guessing): pdfplumber's default table
  strategy infers structure from **ruled borders**. Many statistical publications typeset tables
  with **dot leaders and whitespace alignment** and no rules at all. On Fed MPR p65 the default
  strategy returned a **1x3 fragment** (`['2023','2024','2025']`) of a genuine **31x5 table** —
  108 of 111 populated cells lost.
- **The dangerous part, and the reason this is worth writing down:** that loss was logged
  *nowhere*. My breakage detector only flags tables that come back empty, ragged, or raising. A
  1x3 table is none of those, so it passed as a success. The ingestion report was therefore
  **overstating its own reliability** — which is precisely the failure this project is supposed
  to be resistant to.
- Fix: added a gated **text-strategy fallback** (`# DECISION` documented in
  `src/ingest/tables.py`) — fires only when the lines strategy finds nothing usable on a page
  that still reads as numeric, and each recovered table must pass a plausibility filter
  (min rows/cols + digit density) so prose is not carved into pseudo-tables. Rejected using the
  text strategy everywhere (floods the store with prose-shaped fake tables, inflating the
  ingestion numbers dishonestly) and camelot (needs Ghostscript, absent here — and would not fix
  the borderless case anyway).
- Result after re-ingestion: `fed_monetary_policy_report` 131 → **12,091 cells**;
  `usda_wasde` 329 → **20,353 cells**; `oecd_economic_outlook` 5,553 → **10,958 cells**.
- **Residual honesty note carried into `results/ingestion_check.md`:** the *general class* of
  silent partial extraction is still not detected. One instance was found and fixed; the report
  now states plainly that the true breakage count should be assumed higher than the number it
  prints, because there is no per-table ground truth to check against.
- Also added a full-rebuild wipe at the start of ingestion — table/chunk inserts are additive,
  so re-running without it would have silently doubled every cell (caught before it happened,
  not after).

### What the fallback costs (found by inspecting recovered tables, not assumed)

- After celebrating the recovery numbers I went and *looked* at what was recovered. The text
  strategy infers column boundaries from whitespace, and on tightly-spaced tables it sometimes
  puts a boundary **inside a number**: on WASDE p12, `Area Planted` 2026/27 = **106.2** was
  stored as two cells `10` and `6.2`, and `95.4` as `9` and `5.4`. Adjacent rows in the same
  table came through correctly (`Beginning Stocks` 47.9 / 42.3 / 57.2, `Production` 391.1 /
  447.5 / 419.7 — all verified correct against the source).
- Net assessment, recorded honestly rather than spun: the fallback trades *whole tables silently
  lost* for *some values split across columns*. That is a real gain, because a split value fails
  loudly at compute time while a lost table produced no signal at all — but it is **not clean
  recovery**. Consequence for Phase 3: every gold-set cell must be eyeballed against the source
  PDF, never trusted just because it is in the store.
- Corpus measurement of the related problem: **16.2%** of non-empty cells (8,527) contain two or
  more numbers merged into one cell (worst: OECD annex 3,007, Treasury MTS 1,091, BEA GDP 1,037).
  These **fail safe** — `parse_cell` leaves them as text, so `compute.fetch_cell` raises
  `ComputeError: cell is not numeric` rather than computing something wrong. 53.9% (28,416
  cells) are clean single numbers, which is an ample base for a 20-question gold set.
- Units: only **147 of 34,759** numeric cells carry a unit, because units almost always live in
  the column header rather than the cell. This strongly confirms the gap documented in
  `parse_cell.py` and makes a unit-error planted claim (Phase 3) very likely to expose a real
  Phase 4 miss.

### Phase 2 progress and two bugs found by running it

- Built router (rules-first + LLM fallback), prose path, numeric plan→compute path, multi-doc
  path, `answer()` interface, and the `python -m src.qa.ask` CLI.
- **Bug 1 (caught by the guard, then designed out):** asked for raw `doc_id`/`table_id` strings,
  the 7B model returned the doc_id in the table_id field. The allow-list guard correctly refused
  to compute over an invented table — the right behaviour, but a useless answer. Changed the
  prompt to label candidates `TABLE 1..N` and have the model return an integer, which removes
  the entire id-transcription failure class. The guard is retained.
- **Bug 2 (found by reading the failing output, not by assuming):** the next run picked a cell
  that did not exist (`r1c2` in a 2-column table). Cause: cell values can contain embedded
  newlines, so a single logical row rendered as ~20 physical lines and destroyed the r/c grid
  the model counts against. Fixed by collapsing whitespace and capping cell width in
  `render_table_grid`.
- Latency note for Phase 5 planning: top_k=5 candidate tables put a numeric question at ~50s on
  this M1; top_k=3 brought it to ~26s. Recorded as a `# DECISION` in `answer.py` since it
  directly affects whether the 20-question x 3-rung ladder is feasible.
- **Corpus reproducibility issue confirmed in practice:** the `census_housing_vacancies` rolling
  URL (the one exception flagged at download time) now serves **Q2 2026** data, not the 2024 data
  a fixed corpus would want. This is the predicted link-rot behaviour actually occurring, not a
  hypothetical — it needs a decision from the user (pin a dated Census archive URL, or drop the
  document) before the gold set is written against it.

### Bug 3 — retrieval was serving junk tables (found by following a failure, not by guessing)

- A corn-production question failed with `cell not found ... p35_t1 r1c1`. Rather than treat that
  as the planner being dumb, I checked the table it had been given: a **2-cell** "table" whose
  single populated cell held an entire newline-crammed column of numbers. The planner had no
  valid coordinate to pick. The real WASDE table existed but lost the retrieval ranking to junk.
- Measured the scale of the problem across the store: of **939** detected tables, **63.7% contain
  zero cleanly-numeric cells** and 44.7% have <6 non-empty cells; only **260 (27.7%)** are real
  numeric tables. pdfplumber's detector fires on page furniture, figure captions and cover-page
  layout blocks, all of which were sitting in the retrieval index competing with real data.
- Fix: a quality gate on the **retrieval index only** (>=6 non-empty cells AND >=4 clean numeric
  cells), documented as a `# DECISION` in `src/qa/table_index.py`. Index went 939 -> 260 tables,
  and all 16 documents remain represented. Deliberately **not** filtered at ingestion time: the
  raw store must stay a faithful record of what pdfplumber produced, or the breakage honesty
  required by constraint #5 becomes a fiction.

### Bug 4 — sparse grids led the planner onto blank cells

- Next failure: `cell is blank: usda_wasde_2026_06/p9_ft0 r15c4`. Correct document, correct
  table, blank coordinate. Cause: text-strategy fallback tables carry wide empty spacer columns,
  so the rendered grid was mostly whitespace and the planner mis-targeted.
- Fix: `render_table_grid` now drops entirely-blank rows/columns **from the rendered view while
  preserving each surviving row/col's true index in its label**, so plans stay directly
  checkable against the store. Same WASDE table now renders as a dense, legible grid.
- Pattern worth noting across bugs 1-4: every one of these was surfaced by the system **refusing
  to answer** rather than by producing a wrong number. The constraint-#2 design (model plans,
  Python computes, refuse on any mismatch) turned four separate silent-corruption paths into
  four loud, diagnosable failures.

### Bug 5 / redesign — cell addressing changed from coordinates to enumerated selection

- Blank-lane suppression reduced but did not eliminate the blank-cell failure, because blank
  *intersections* of populated rows and columns still exist. Rather than keep patching, changed
  the addressing scheme: the planner now picks from an **enumerated list of that table's actual
  numeric cells** — `[7] 254.51 (row: "2025/26 (Est.)" | column: "Ending Stocks")` — and returns
  a cell id. Python maps the id back to (row, col).
- This makes an out-of-range or blank selection **structurally impossible** rather than merely
  detectable, and turns a 2D spatial-reasoning task (which small models are weak at) into a
  selection task. Constraint #2 is unaffected — arguably strengthened, since the model can now
  only ever point at a cell that exists and holds a number. Guards retained and verified: an
  invented cell id is still refused with an explicit message.
- **What building this exposed (the more important finding):** the enumerated view makes cell
  *labels* visible, and they are poor on text-fallback tables — WASDE p8 cells carry row labels
  like `"Total G"` and column headers like `"e 2026"`, i.e. the fallback recovers **values but
  fragments the labels that identify them**. Lines-strategy tables are clean by comparison
  (FDIC p13: row `"Construction and development"`, column `"All Insured Institutions"`).
- Split of the 260 retrievable tables: **198 lines-strategy (good labels) vs 62 text-fallback
  (fragmented labels)**. Consequence for Phase 3, recorded now so the gold set is not built on
  sand: **numeric gold questions should be drawn primarily from lines-strategy tables**, and any
  question drawn from a fallback table needs its cell verified against the source PDF by eye.
  The fallback's value is that it stopped whole documents from being invisible; it is not a
  source of clean, self-describing cells.

### THE most important finding so far: a confidently-cited WRONG answer

- The numeric path finally produced a complete answer end-to-end: question "What was the
  noncurrent loan rate for construction and development loans at all insured institutions?" →
  **0.38**, `operation=lookup`, cited to `fdic_quarterly_banking_profile_2024q1 p12 p12_t0 r4c1`,
  **confidence 0.753**, with a fluent planner rationale naming the right row and column.
- I checked it against the source PDF instead of accepting it. **It is wrong.** The true answer
  is **0.60**. Cell r4c1 does hold 0.38, and its row label really is "Construction and
  development" — but that row sits under the section banner **"Percent of Loans 30-89 Days Past
  Due"**, not "Percent of Loans Noncurrent". The system returned a different metric's number,
  with a real citation to a real cell, at moderate-high confidence. This is precisely the failure
  mode the whole project exists to prevent, and it survived every guard built so far.
- **Mechanism (two compounding defects):**
  1. **No section context in the schema.** `tables(...)` records a *column* `header` but nothing
     for the *section banner* that spans a block of rows. FDIC Table V-A stacks several metric
     blocks in one detected table, each repeating identical row labels, so "Construction and
     development" is ambiguous across metrics and the planner took the first match.
  2. ~~**An entire section was silently dropped by extraction.**~~ **← THIS DIAGNOSIS WAS WRONG.
     Corrected below.**

#### Correction: my first diagnosis of defect (2) was wrong

I originally concluded that the "Percent of Loans Noncurrent" section had been *dropped* by
extraction, on the evidence that no cell in `p12_t0`/`p13_t0` contained the string "Noncurrent"
and only three section banners were detectable. That inference was too quick — absence of the
*banner* is not absence of the *data*.

The user pushed back and named the real mechanism: **label loss, not data loss.** Checking the
store row by row confirms it. The Noncurrent block's numbers were in `p12_t0` the entire time —
`r17 col1 = 0.6`, exactly the value I had gone looking for — sitting in a **vacant-label row**
(col0 empty, value present). The table alternates fully-labelled rows with vacant-label rows
that are the second half of a visually two-line row whose label pdfplumber discarded, and the
section banner row (`r15`) came back with zero populated cells.

So the correct statement is: *the value was present and unreachable, not missing.* That is a
meaningfully different defect with a different fix — recover the labels, rather than re-extract
the data. Worth recording that the first read of the evidence was wrong, because the wrong
diagnosis would have sent the fix in the wrong direction.
- Partial fix applied: `list_numeric_cells` now detects section banners (a row whose only
  populated cell is a non-numeric label) and attaches `section` to every enumerated cell; the
  planner prompt now tells the model the same row label repeats across sections and that the
  section decides the metric. Verified working — "Construction and development" at col 1 now
  resolves distinctly to 0.38 (30-89 days) vs 0.04 (charged-off).
- **Not fixed, and stated plainly:** the dropped Noncurrent section is still missing, so this
  specific question remains unanswerable from the store. The fix removes the *ambiguity* defect,
  not the *missing data* defect. Retrieval/extraction for multi-section tables needs more work
  before the Phase 3 gold set is finalised.
- Consequence for the confidence formula: confidence 0.753 on a wrong answer shows the current
  formula measures *retrieval agreement and path auditability*, not correctness. It is not
  calibrated, and Phase 4's "what verifies the verifier" section should say so with this example
  rather than claiming a calibration the numbers do not support. **Parked durably in
  `results/known_limitations.md` (L1)** so it reaches MEMO §4 rather than being lost between
  phases.

### The fix: label-loss repair pass + completeness detector

- **Repair pass** (`src/ingest/tables.py`): for a lines-strategy table showing the vacant-label
  symptom, rebuild it from `page.extract_words()` clustered by `top` (3pt tolerance) and bucketed
  into columns using the page's own vertical rule x-positions — deliberately not via
  `find_tables()` cell objects, since those are what lost the labels. Applied as a **repair, not
  a replacement**: it only touches tables exhibiting the symptom, so fully-labelled tables cannot
  regress.
- **Completeness detector** (constraint #5): every row still holding values without a label is
  written to `results/ingestion_check.md` as an `INCOMPLETE:` entry, and every successful repair
  as `REPAIRED:`. This is the part that converts "found by chasing one wrong answer" into
  something the pipeline reports on its own.
- **Detector v1 over-fired badly and I caught it before trusting the numbers.** The first version
  tested only col0 and ignored the header zone, so it reported **284 unlabelled rows on BEA GDP
  alone** — nearly all false positives: BEA stacks multi-tier column headers (legitimately no row
  label) and puts a line number in col0 with the actual label in **col1** ("43 | Net exports of
  goods and services"). Tightened to skip the header zone and to accept a label in col0 *or*
  col1. Same document then reported **10**. A breakage log that cries wolf is its own kind of
  dishonesty — it buries the real entries — so precision mattered more than recall here.
- **Narrow validation first** (FDIC p12-13, as scoped): vacant rows 26 → 1 on both pages; all
  five Table V-A blocks now carry labels ("Percent of Loans 30-89 Days Past Due", "Percent of
  Loans Noncurrent**", "Percent of Loans Charged-Off (net, YTD)", "Loans Outstanding (in
  billions)", "Memo: Other Real Estate Owned"). "Construction and development" now resolves
  distinctly to **0.38 / 0.60 / 0.04 / 498.5**. Residual vacant rows are page furniture
  ("2024 VOLUME 18 NUMBER 2"), not data. Also merged consecutive banner rows, since a wrapped
  title ("Percent of Loans Charged-Off" / "(net, YTD)") was registering as two sections.

### Full-corpus re-run and re-audit (before → after)

| metric | before | after |
|---|---|---|
| table cells | 118,836 | **119,077** (+241) |
| tables | 939 | 939 (unchanged) |
| prose chunks | 3,865 | 3,861 (census doc changed) |
| breakage-log entries | 257 | **304** |
| tables with vacant-label symptom | not measured | **38** |
| ...repaired | — | **11** |
| rows still unlabelled | **unknown/invisible** | **249, all itemised** |

- **Re-audit of the "198 lines / 62 fallback" split: unchanged at 198 / 62.** The user expected
  this likely undercounted the fragile bucket; it did not move, because the repair changes table
  *content*, not retrieval *eligibility*. Reporting that plainly rather than manufacturing a
  delta. What the re-audit *did* surface is a genuinely new fragility measure the old split could
  not express: **36 of the 260 retrievable tables still carry unresolved label loss** (BEA GDP,
  FT-900, EIA STEO among them) — that is the real fragile bucket, and it was invisible before.
- The repair fires unevenly by publisher, which is expected and worth stating: FDIC 7/16 and Fed
  MPR 2/2 repaired, but BEA 0/5 — BEA pages carry **no vertical rules at all**, so there is
  nothing to bucket columns against. Those are logged as `INCOMPLETE: ... no vertical rules on
  page to define columns` rather than silently skipped.

### Third failure on the same question, and the fix that finally resolved it

- After the repair, the same question returned **0.44** — still wrong, now sourced from p13. Root
  cause was **not** reasoning: `list_numeric_cells` truncated to the first 40 cells *in row
  order*, which stopped inside the first metric block, so the Noncurrent cells were **never shown
  to the planner**. It could not have answered correctly however well it reasoned; it picked the
  closest visible cell. A truncation artefact presenting as a reasoning failure.
- Fixed by **relevance-ranking cells before truncating** (token overlap between the question and
  each cell's row label + column header + section), then restoring row order for readability. All
  five sections now fit inside the same 40-cell budget.
- **Acceptance test passes:** the question now returns **0.6**, `operation=lookup`, cited to
  `fdic_quarterly_banking_profile_2024q1 p13 p13_t0 r23c1`. Citation verified against the store —
  that cell holds `0.6`, row label "Construction and development", section "Percent of Loans
  Noncurrent**", header "FDIC-Insured All Insured Institutions". Correct answer, correct
  provenance.
- Worth noting the confidence went **down** (0.753 → 0.689) while the answer went from wrong to
  right. That is not a paradox — it is direct evidence for L1: the score tracks retrieval
  agreement, not correctness. It should not be read as a correctness signal in the memo.
