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
