# AI Log

Running log of what the coding assistant (Claude Code) did each phase, and anything it got
wrong that the user corrected. Feeds the AI-disclosure section of `MEMO.md`.

---

## ⚠ CORRECTIONS TO CLAIMS ALREADY REPORTED

Claims stated to the user that later turned out to be **wrong**, listed here rather than only in
the phase logs so they cannot be missed. Each is expanded in place below.

| # | claim as originally reported | what was actually true | found by |
|---|---|---|---|
| 1 | Fix 1's new matcher "can **only inflate**, never deflate" a score | True of the substring matcher it *replaced*; **false of the replacement**, which scores a correct answer as a MISS whenever the figure ends a sentence (`"The rate was 1.3."` vs needle `1.3`). The grader has now produced measurement error in **both** directions. | QC on the first training batch, not by re-reading the matcher — [detail](#a-false-negative-in-the-matcher-i-shipped-as-fix-1-self-caught-and-it-corrects-something-i-told-the-user) |
| 2 | FDIC's Noncurrent section was "silently dropped" by extraction | Section was present; the real mechanism was **vacant-label rows** (value present, label dropped). `p12_t0 r17c1 = 0.6` was there all along. | the user corrected me |
| 3 | A reranker was the right next fix | Measured that 7 of 9 failures were **post-retrieval**, so a reranker could fix at most 2. I disproved my own recommendation. | my own measurement |
| 4 | Multi-doc design 3 was "a failure" | Declared from **one** data point; M04 later passed via that exact path. Multi-doc is 1/4, not 0/4. | later evidence |
| 5 | Four fixes would take the gold set to 17–18/20 (later 12–15/20) | Delivered **11/20** — net zero. Over-confident inference from partial evidence. | the measurement itself |

**Item 1 is the one that most affects reported numbers** and is going on the Sunday call: Stage 1's
11/20 and 8/9 were produced by a grader that has since been shown wrong twice, so those figures
carry that caveat rather than standing as clean results.

---

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

## Phase 5 — Quantization ladder (1D)

### The router bug that would have invalidated the whole ladder

- A 2-question smoke test (`--limit 2`) returned `'1'` for a prose question. Following it up with
  an instant rules-only routing check over all 20 gold questions showed **routing accuracy of
  60% — 7 of 8 prose questions misrouted to the numeric path**.
- Cause: `NUMERIC_CUES` contained a bare `\d`. Every question about economic data contains a
  year ("in the first quarter of 2024"), so the digit cue fired on essentially everything.
- **Why this mattered more than a normal bug:** the ladder forces rules-only routing so that
  routing noise cannot confound an INT4-vs-INT8 comparison. Had I gone straight to the full run,
  INT4 would have scored badly and the ladder would have been measuring *my router*, not
  quantization. The cheap smoke test paid for itself immediately.
- Fixed by requiring cues that indicate a *table lookup* rather than the mere presence of a
  number, and by dropping a generic `what was the ...` prose cue that matched nearly every
  question while cancelling specific numeric cues one-for-one. **60% → 90%.**
- The residual 2 are genuinely undecidable from question text: "what was the homeownership rate"
  *sounds* like a table lookup, but that figure lives in a sentence. Added a numeric→prose
  fallback for weakly-routed questions, which fixed them end-to-end.

### Multi-doc: three designs, three distinct causes, then stopped

Multi-doc scored **0/4**. It is not quantization damage — the path could not answer these
questions by construction. Three attempts, each failing for a different reason:

1. **numeric-only, prose on `value is None`** — the prose arm was *dead code*. The numeric path
   always returns *a* number; observed junk values 9, 2,022 and 159.2 pulled from topically
   related but wrong tables.
2. **numeric first, prose when confidence < 0.55** — never fired. Measured table retrieval
   scores: M01 0.719, M03 0.789, M04 0.704, indistinguishable from a genuine numeric lookup.
   **The lesson: retrieval score measures topical relevance, not which representation holds the
   answer.** An FDIC net-income question legitimately matches FDIC tables strongly even though
   the figure lives in the narrative. No threshold can separate those.
3. **prose-first, numeric fallback** — still took the numeric arm, because doc-filtered prose
   retrieval returned `NOT_IN_CONTEXT`. A third distinct cause, this time inside the filtered
   retrieval rather than in arm selection.

**Decision: shipped as a documented weakness rather than attempting a fourth fix.** It is 4 of
20 questions, each failure is understood at mechanism level, and citation coverage stayed 4/4
throughout — the system cited real sources on every question it got wrong, which is itself worth
recording as a caution against reading citation coverage as a quality signal.

### A wrong "major finding" I retracted before acting on it

While diagnosing multi-doc I reported that retrieval was returning entirely wrong documents for
M01/M03 (top hits: census poverty, USDA prices; correct sources absent). I re-ran before acting
on it and the real code path retrieved correctly — 0.761 `bea_gdp`, 0.751 `fed_mpr`. The bad
result came from **my ad-hoc test script's import order**, not from the system. Recorded because
the instinct that mattered was verifying a dramatic result before building on it.

### Methodology mistake: I contaminated a running measurement

Running embedding queries to investigate scores *while* a benchmark held the 7B model produced a
hard GPU failure: `kIOGPUCommandBufferCallbackErrorOutOfMemory`. Two consequences, both worth
stating:

- **My error.** No concurrent GPU work during benchmarks. It also means the earlier 494 s
  latency outlier is suspect and should not be quoted as a clean measurement.
- **Genuine evidence.** An 8 GB M1 cannot hold the 7B INT4 model and a 130 MB embedding model on
  the GPU simultaneously without the allocator failing. That is a harder, more citable data
  point for the deployment recommendation than the weight arithmetic alone.

### Measurement findings before any rung was run

- **`ps` RSS is useless on Metal**: ~50 MB reported against ~5.6 GB `footprint` for the same
  loaded model, because unified-memory buffers are not counted in RSS. Switched the harness to
  report `footprint` alongside `mx.get_peak_memory()`.
- The MLX-vs-OS gap measured **0.31–0.68 GB** (MLX under-reporting), *not* the ~2x the build spec
  warned about. Reporting the measured figure rather than the expected one.
- **Checkpointing was added after losing a 19/20 run** to session teardown, because results were
  only written at the end. Now every question is flushed to a `.jsonl` as it completes, with
  `--resume`. Verified it survives a torn final line from a hard kill.
- KV-cache arithmetic (`results/kv_math.md`) is computed from the model's own config: **56
  KB/token**, and with GQA (4 KV heads, not 28) a reader assuming MHA would overstate KV memory
  by **7x**. At 4k context only **2 concurrent users** fit on this machine.

## Phase 4 — Verification layer (1C)

- Built `src/verify/verify.py` (claim → verdict + citation + confidence) and
  `src/verify/score.py` (precision/recall + 3-way confusion matrix → `results/verification_report.md`).
- `supported` / `contradicted` / `unverifiable` are separated **structurally**: the code decides
  first whether any evidence was found at all, and only then whether that evidence agrees.
  Collapsing "I found nothing" into "this is false" is the tempting shortcut here, and it would
  let a verifier score well against planted errors while actually measuring its own retrieval
  failures.
- **First run was bad and the numbers said so: precision 0.300, recall 0.500, exact-match 0.400.**
  It returned `contradicted` for 10 of 15 claims, 7 of them wrongly. I did not ship that as an
  "honest limitation" — a verifier that contradicts almost everything is broken, not modest.
- Diagnosis by reading the per-claim basis strings rather than the headline metric:
  1. **The claimed number was taken as the first number in the sentence.** Claim 12 ("official
     poverty rate in 2022 was 11.5 percent") was compared against **2022**, the year.
  2. **Cell matching was far too loose** (2 overlapping terms, whole-word only). Claim 8's "net
     charge-off rate for credit card loans" matched the *30-89-day* credit-card cell (1.55)
     instead of the charged-off cell (4.7), because "charge-off" and "Charged-Off" share no
     whole-word token.
  Together these manufactured contradictions out of the verifier's own matching failures — a
  failure mode that is **invisible in recall** and shows up only in precision, which is exactly
  why the positive class and both metrics have to be reported.
- Fix: a numeric recompute may now decide a verdict only when the match is **strong and
  unambiguous** — ≥3 distinctive non-stopword terms overlapping with prefix tolerance
  (so charge/charged agree), the winning cell must beat the best cell from any *other* row by a
  margin, bare 4-digit years are excluded as period markers rather than measurements, and the
  cell is compared against **all** numbers in the claim rather than the first. If any condition
  fails the code returns nothing and falls through to text-based verification instead of guessing.
- Verified in isolation before spending another full LLM run: claim 6 now matches 0.6 vs claimed
  0.85 (correct contradiction), claim 8 matches 4.7 vs 4.7 (correct support), and claims
  1/2/4/5/9/10/12/15 fall through to the text path instead of manufacturing contradictions.
- **A first-run "success" that was actually luck, now removed.** Claim 10 (the planted unit
  error) was scored `contradicted` in run 1 — but the basis string reads "recomputed 0.0 does not
  match claimed 498.5", i.e. it matched an unrelated cell and got the right verdict for entirely
  the wrong reason. After the fix it no longer matches any cell confidently, which should expose
  the genuine unit-error miss predicted in the answer key. Worth recording that the first run's
  score flattered the system on this claim.

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

### L3 — extending the same verify-against-source mechanism to number splits

- Built `src/ingest/verify_cells.py`: the same "check the store against the source page text"
  idea as the L2 completeness detector, pointed at a different signature — the text-fallback
  cutting a column boundary through the middle of a number.
- **Two false-positive traps, both caught before trusting the output.** They matter more than the
  final counts, because either would have made the detector confidently misleading:
  1. **Float precision.** Normalising with `float()` silently rounds above 2^53, so concatenating
     two 9-digit FDIC cells gave an 18-digit value that rounded into a match with an unrelated
     page token. *Every* split flagged on FDIC came from this — on a lines-strategy document that
     structurally cannot have fallback splits, which is what made it obvious something was wrong.
     Replaced with exact string canonicalisation (unit-tested, including the 18-digit case).
  2. **Validating an artefact against its own artefact.** Short integers concatenate into other
     real page numbers by coincidence (`'93'+'5'` → `935`), and — worse — `extract_text()` merges
     adjacent wide columns exactly the way the table extractor does, so the "source of truth" I
     was checking against carried the same defect. Fixed by requiring the observed signature: the
     decimal point lands in the second fragment and not the first (`106.2` cut into `10` | `6.2`).
     Corpus flags went from **294 (nearly all spurious) to 14**, all eyeball-verified.
- **Suppression, not deletion.** Flagged fragments are withheld from `list_numeric_cells` so the
  planner cannot compute on `10` when the page says `106.2`, but they stay in `tables` — same
  principle as the junk-table retrieval gate: the raw store stays a faithful record of what
  extraction produced, or constraint #5's honesty becomes a fiction.
- The broader `orphan-number` signal (391 cells: purely-numeric cells whose value appears nowhere
  on their source page) is **recorded but not used to hide data** — it is too noisy to justify
  suppressing on, and saying so is more useful than pretending it is actionable.
- **Unexpected bonus, found while inspecting the suppression.** WASDE p12 held the *correct*
  value `106.2 *` in col8, right beside the fragments — unusable only because the trailing
  footnote marker made the cell fail the numeric test and be stored as text. `parse_cell` now
  strips trailing footnote/status markers (`*`, `**`, `r` revised, `p` preliminary) when what
  remains still parses as a number. Verified after re-ingestion: row 12 now offers
  `101.8 / 110.1 / **106.2**` and hides `10` / `6.2`. So the pass did not just prevent a wrong
  answer, it restored the right one. Unit-tested against negative cases so genuine text cells
  ("Total loans", "All Other", "Q1") are untouched.

---

# STAGE 2 — Improve the Model

## Phase 2A Step 0 — expanded multi-doc eval set

- Built `eval/multidoc_expanded.json`, 35 hand-authored multi-doc questions, because Stage 1's
  multi-doc sample cannot measure a fine-tuning effect: n=4 gold means one question is worth 25
  points, n=1 held-out means one question is worth 100. Generating 500 training examples to move
  an unreadable metric would have been wasted effort.
- Setup pulled forward per the brief so nothing blocks at 11pm: Qwen2.5-3B-Instruct-4bit (1.6GB),
  ARC-Challenge/Easy parquet (1,172 test questions), `pyarrow` pinned.

### The composition mistake — caught by self-check, before review

**What I built first:** 35 questions that all *looked* like multi-doc questions. They were phrased
as comparisons ("Compare X with Y", "The report gives A and B — state both"), they had multiple
`expected_citation` entries, and every expected figure verified against source. On a read-through
they passed.

**What was actually wrong:** only **7 of 35 spanned two or more distinct documents.** The other 28
paired two facts drawn from the *same* document — often two figures from the same paragraph. Those
are two-fact extraction questions wearing multi-doc clothing. They do not require combining
information across sources, which is the entire capability under test.

**How I caught it:** not by re-reading the questions, which is what had already failed. I ran a
composition check over my own output — counting `len({c['doc'] for c in q['expected_citation']})
>= 2` per question — and got 7/35. The mechanism that made this invisible to review is that
multiple `expected_citation` entries look correct at a glance whether or not the `doc` values
inside them differ; the defect lives in a field comparison, not in the prose.

**Why it mattered:** this set is the yardstick the entire fine-tune is measured against. Had it
shipped, 2C(i)'s before/after would have been measuring two-fact extraction and reporting it as
multi-doc reasoning. A fine-tune could have "succeeded" on a capability it never touched, or
failed on one it never tested — and either result would have been reported with a straight face.
Worse, the eval was authored *by me* and reviewed *by me*, so the same blind spot sat on both
sides of the check.

**Fix:** rebuilt to **26 cross-document + 9 same-document controls**. The controls are deliberate,
not leftovers: if the fine-tune lifts cross-document questions but leaves controls flat, the gain
is specific to multi-document reasoning rather than to two-fact extraction generally. Without
controls those two explanations are indistinguishable.

**Generalisable lesson, which is why this is worth the space:** a check that re-reads the artifact
cannot catch a defect that is invisible in the artifact's surface form. Structural properties need
structural checks — count the thing, don't eyeball it. The same pattern produced Stage 1's most
valuable findings (counting where evidence was at failure time, rather than assuming retrieval was
the problem).

### Contamination control
Enforced at the **fact** level rather than the document level, because document reuse is
unavoidable in a 16-document corpus but figure reuse is not. Text 5-gram Jaccard vs all 29
existing eval questions peaked at **0.143** against a 0.60 threshold (0 above). Where a figure
recurs it is always paired with a fresh figure from a different document, so no item is answerable
from memory of an earlier one. Ground truth verified: all 35 questions had every expected figure
confirmed present in the text of its own cited source page.

### A measurement that changed the plan
While writing up the pre-registered caveat I tested whether **query decomposition** rescues the two
failures I had classified as out of scope for fine-tuning. It does — 2 of 2:

```
case         compound-question   decomposed   verdict
M03-FDIC     not retrieved       retrieved    DECOMP FIXES IT
H09-EPA      not retrieved       retrieved    DECOMP FIXES IT
M01-BEA      retrieved           retrieved    (its failure was reasoning, as diagnosed)
```

So my "half of multi-doc is structurally out of scope" framing was too pessimistic in an
interesting way. The retrieval failures were **caused by** the compound question shape — a 40-word
question naming two documents produces a diluted embedding, and once filtered to one document the
right chunk no longer ranks. One root cause, surfacing at two different layers. Recorded before
training rather than discovered after, and it directly sharpens what 2C(iii) has to decide.

### Grader scoring-validity flaw — found in Stage 2, present in Stage 1, disclosed against our own interest

**What the flaw was.** Answer grading used naive substring membership (`needle in answer`). A
needle therefore matched inside any longer number containing it:

```
needle "1.3"  matched inside  "1.36 percent"     -> a WRONG answer scored CORRECT
needle "5"    matched inside  "15.2", "45.1", "22.5", "13.3", ...
```

**How it was found.** Not by reading the grader. The Stage 2 dependency check reported that 3 of
26 cross-document eval questions appeared answerable from a single document. Tracing *why*
`"1.3"` was allegedly present on an FDIC page led to `"1.36 percent"` — a substring artifact. Two
of those three "failures" were the matcher misbehaving, not the questions. The same artifact that
corrupted the check would corrupt real grading, and more damagingly: it can only ever turn a
**wrong answer into a pass**, never the reverse.

**Fix.** `src/eval_match.py` — needles now match only as complete numbers (not preceded or
followed by a digit or decimal point), with comma normalisation so `12,419.3` matches `12419.3`.
Applied globally at the single grading site rather than patched per-caller. Unit-tested on 14
cases including every observed failure mode.

**STAGE 1 IMPLICATION — stated plainly, and it cuts against us.** This flaw was present when
Stage 1 was scored and submitted. Seven Stage 1 questions carry needles short enough to be
affected:

| set | question | needles |
|---|---|---|
| gold | P01 | `1.3` |
| gold | **P05** | **`5`** |
| gold | P08 | `68` |
| gold | M01 | `1.3`, `5` |
| gold | M04 | `68` |
| holdout | H01 | `1.1`, `27.1` |
| holdout | H03 | `73` |

**P05 is the clearest concern**: its only needle is a bare `"5"`, which matches inside essentially
any number, so its recorded pass may be a false positive. M01 shares that needle but was scored a
miss regardless, so its verdict is unaffected.

The direction matters. Because substring matching can only inflate scores, **every affected
question is a possible false PASS and never a false FAIL.** The correction therefore moves the
Stage 1 numbers — 11/20 gold, 8/9 held-out — in the **less flattering** direction, not the more.
The true figures may be slightly lower than reported.

**Decision: Stage 1 is not being retroactively edited.** It is submitted and graded, and quietly
restating its numbers after the fact would be worse than disclosing the flaw. This is recorded
here, will be disclosed on the walkthrough call, and the fixed matcher governs all Stage 2
scoring from this point forward. Finding a bug that makes your own submitted results look better
than they were, and saying so unprompted, is the only defensible way to handle it.

---

## Stage 2, Phase 2A Step 2 — training data generation

### A false-negative in the matcher I shipped as Fix 1 (self-caught, and it corrects something I told the user)

Fix 1 replaced substring needle matching with complete-number matching. When I reported it I
said the change could **"only inflate, never deflate"** a score. That was true of the substring
matcher being replaced. It was **not** true of my replacement.

The boundaries `(?<![\d.])` / `(?![\d.])` reject any adjacent period — including a sentence-final
full stop:

```
matches_needle("The rate was 1.3.", "1.3")  -> False    # correct answer scored as a MISS
```

So the matcher I shipped introduces **false negatives**: a correct answer is marked wrong whenever
the figure lands at the end of a sentence, which is exactly where answers put figures.

**How it surfaced.** Not by reading the code. QC on the first training batch rejected 168 examples
as "answer text is missing a figure the template guarantees is there". The data was fine; the
matcher was wrong. A defect in a checker is invisible to a re-read of the checker — it only
appears when something independent disagrees with it. Same lesson as Stage 1's L2/L3, now applied
to my own verification tooling rather than the pipeline.

**Fix.** Boundaries now reject only a real numeric continuation: an adjacent digit, or a period
followed by a digit. Unit tests 14 -> 22 cases, six of them sentence-final regressions. All three
eval-set checks re-run under the corrected matcher; conclusions unchanged (26/26, 35/35, 0 leaks).

**Consequence for the Stage 1 disclosure.** The disclosure already recorded stands, but its framing
needs one correction on the call: the *substring* bug inflated only. My *replacement* could deflate.
Both directions of error have now existed in this grader, and the honest statement is that the
grader itself has been a source of measurement error twice — which is an argument for reporting
Stage 1's numbers with that caveat attached rather than as clean figures.

`src/eval_checks.py` was promoted from an ad-hoc heredoc to a committed script, because it has
gated a go/no-go decision twice and must be re-runnable whenever the matcher changes.

### Three generator defects QC caught, fixed at source

1. **Topic extraction returned a placeholder instead of failing** — produced questions reading
   "state the reported figure and the reported figure". 325 rejections.
2. **Years used as answer figures.** `2025` is not a measurement; it recurs on nearly every page so
   it can never be attributed to one excerpt. 151 rejections. **Same bug class as the Stage 1
   router defect**, where a bare `\d` cue fired on every year — I reintroduced a pattern I had
   already been burned by once.
3. **Citation headers matched as document text.** Doc_ids containing digits
   (`oecd_economic_outlook_116_annex`) made the figure `116` "appear" in every OECD excerpt via its
   label. Grounding must mean present in the text, never in the label.

### A methodological problem I created by fixing those, and how I handled it

Fixing the generator moved every check upstream, so the QC rejection rate fell to 0.1%. A gate that
rejects nothing is indistinguishable from a gate that checks nothing — I had accidentally destroyed
my own evidence.

Rather than assert the gate still works, I added `--no-prefilter` to disable the generator's guards
and ran the **same unmodified QC** against an unguarded batch: **78.4% rejected** (549 of 700), vs
0.1% on the clean batch. Both numbers are reported. Either alone would mislead.

### Deliberate design decision: ~24% of examples are genuine negatives

Training only on "answer the half you can" would teach the model that `NOT_IN_CONTEXT` is always
wrong. Stage 1's abstention behaviour is load-bearing — the verification layer and the confidence
signal both depend on it — and destroying abstention to fix multi-doc would trade one failure class
for the confidently-wrong-answer class that Stage 1 spent its entire fix budget eliminating.
QC therefore also verifies that each negative's context genuinely lacks both asked-about figures;
43 examples failed that check in the ablation and would have taught the model to refuse questions
it could answer.

### Stated limit on diversity

13 template skeletons bound the *syntactic* variety, even though all 699 questions are textually
distinct (mean pairwise 5-gram Jaccard 0.009) because their subject matter is drawn from the real
corpus. A model could overfit the skeletons rather than the task. The eval set is hand-authored and
shares none of these templates, so that failure mode would show up as a flat eval result — it is
detectable, not hidden.

## Stage 2C — verification pass corrections

Two claims I reported that the verification pass overturned:

**1. ARC "0.0% — catastrophic forgetting" was wrong on both the number and the framing.**
The regression harness generated with `max_tokens=8`. That fits the base model (a bare letter) but
truncates the fine-tuned model's 20-40 token replies before any answer letter appears. Re-ran all
120 questions at 64 tokens for BOTH arms with a hardened extractor: base **97/120 (80.8%),
identical to the 8-token run** — the control showing the budget change did not inflate the baseline
— and tuned **3/120 (2.5%)**. The honest figure is 2.5%.

The framing was also wrong. "Catastrophic forgetting" implies degraded reasoning. Of 29 sampled
outputs re-generated in full, **zero were valid multiple-choice answers picking the wrong option**.
97/120 begin with `NOT_IN_CONTEXT`; the rest emit document-citation language ("This document gives
decomposers as the answer (C)... not covered by the text provided") on a task with no documents,
citing page numbers that do not exist. That is **output-format collapse**, a narrower and more
specific failure. Whether the underlying knowledge survived is not measured by this suite.

**2. "Fine-tuning was the wrong tool here" is not supported by what was run.**
A 20-example random sample of the training set found **0 of 20 examples that ever presented two
documents**; the generator has no example kind that does. The training data was structurally
single-document throughout, so cross-document combination was never demonstrated to the model.

The accurate claim: *this fine-tuning attempt never trained the target skill.* What it produced was
general-purpose abstention, which explains the cross-doc gain (2/26, matching prompting), the
control collapse, and the ARC regression together. **Whether fine-tuning with genuine two-document
examples would perform differently remains untested.**

This one is worth dwelling on. "Fine-tuning was the wrong tool" was **pre-registered before
training** as a plausible honest outcome, with a mechanism attached. When the numbers came in it
looked confirmed, and I reported it as such. The pre-registration made a wrong conclusion *more*
tempting rather than less — it gave me a ready-made story that fit the data without requiring me to
check whether the experiment had tested what the story claimed. Pre-registering a hypothesis does
not license accepting it; it only stops you inventing one afterwards.

Both corrections were prompted by user-directed verification checks, not by my own review.
