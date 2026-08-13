# Stage 1 — Progress Checklist

Legend: `[x]` done · `[~]` in progress · `[ ]` not started · `[!]` blocked on you

Last updated: CLOSEOUT COMPLETE — all 4 deliverables covered, MEMO.md written.

---

## Phase 0 — Setup & offline proof `[x] COMPLETE`

- [x] conda env `doc-intel` (Python 3.11 — system default 3.7 too old for `mlx-lm`)
- [x] deps installed + pinned in `requirements.txt`
- [x] MLX sees Metal GPU → `Device(gpu, 0)`
- [x] `Qwen2.5-7B-Instruct-4bit` downloaded (~4.0 GB)
- [x] offline generation proven (`HF_HUB_OFFLINE=1`)
- [x] baseline recorded: **~9 tok/s warm, 4.41 GB peak** → `results/phase0_offline_proof.md`
- [x] repo skeleton, `.gitignore`, `AI_LOG.md`

## Phase 1 — Ingestion `[x] COMPLETE`

- [x] `download_corpus.py` — 16 PDFs, every URL verified by real fetch
- [x] census doc pinned to Q1-2024 archive (rolling URL had drifted to Q2 2026)
- [x] prose chunks, page-anchored (PyMuPDF)
- [x] tables → SQLite `tables(doc_id,page,table_id,row,col,value,unit,header)` (pdfplumber)
- [x] FAISS prose index + separate table-retrieval index (260 usable of 939)
- [x] `results/ingestion_check.md` with honest breakage log
- [x] **text-strategy fallback** — recovered ~44k cells (Fed MPR 131→12,091; WASDE 329→20,353)
- [x] **L2 label-loss repair** + completeness detector (`INCOMPLETE:` entries)
- [x] **L3 split-number detector** + suppression from answer path
- [x] footnote-marker recovery (`106.2 *` → 106.2)
- [x] `results/known_limitations.md` (L1–L6)

**Totals:** 16 docs · 713 pages · 119,077 cells · 939 tables · 3,861 chunks

## Phase 2 — QA system (1A) `[x] COMPLETE (with one known weakness)`

- [x] router (rules + LLM fallback)
- [x] prose path with `{doc, page}` citations
- [x] numeric path — **model plans, Python computes**, refuses on bad plans
- [x] `answer()` interface + `python -m src.qa.ask` CLI
- [x] enumerated cell selection (removed whole classes of planner error)
- [x] section-header disambiguation (fixed a confidently-wrong answer)
- [x] router cue fix — rules-only routing **60% → 90%**
- [x] numeric→prose fallback for ambiguous routing
- [x] multi-doc path — **1/4 on gold set, 0/1 held-out**; known structural weakness,
      three designs tried and documented in AI_LOG.md

## Phase 3 — Gold set & planted errors (1B) `[x] COMPLETE — REVIEWED & APPROVED`

- [x] `gold_set.json` — 20 questions (8 prose, 8 numeric, 4 multi-doc)
- [x] every expected answer read from **source PDF**, not from the store
- [x] all 8 numeric answers reconcile page ↔ store (8/8 verified)
- [x] `summary.md` — 15 claims, 6 planted errors (one of each required type)
- [x] `answer_key.json` → `answer_key.enc` (Fernet)
- [x] **security fix**: `.gitignore` trailing-comment bug — plaintext key was committable
- [x] **user reviewed every question + planted error — approved 2026-08-12** (spec Phase 3 step 4)

## Phase 4 — Verification layer (1C) `[x] COMPLETE`

- [x] `verify.py` — 3 verdicts, separated structurally
- [x] numeric claims recomputed in Python
- [x] `score.py` — precision/recall + 3-way confusion matrix
- [x] positive class stated explicitly
- [x] `results/verification_report.md`
- [x] honest failure analysis — 3 miss mechanisms documented
- [x] recorded a wrong prediction of mine + a "success" that was luck

**Results:** precision **0.500** · recall **0.333** · exact-match **0.667** · 10/15 verdicts correct
(first run was broken at precision 0.300 — fixed, not shipped as a "limitation")

## Phase 5 — Quantization ladder (1D) `[~] IN PROGRESS`

### Harness `[x] COMPLETE`
- [x] `kv_math.py` — KV-cache + weight arithmetic, instant, no model load
- [x] `results/kv_math.md` written
- [x] `measure.py` — MLX peak + OS footprint + swap delta
- [x] `bench.py` — gold-set runner, `--limit` / `--type` for fast checks
- [x] **checkpointing** + `--resume` / `--fresh` (verified incl. torn-line recovery)
- [x] `ladder.py` — INT8 fetch + load-attempt recorder
- [x] `results/phase5_fix_spec.md` — acceptance criteria fixed in advance

### Pre-benchmark fixes `[~]`
- [x] FIX 1 — checkpointing (a 19/20 run was lost before this)
- [x] FIX 2 — multi-doc prose support — **3 designs tried, all failed. Stopped iterating.**
  - [x] design 1: numeric-only + `value is None` → prose arm was **dead code** (numeric always
        returns *a* number: observed 9, 2,022, 159.2)
  - [x] design 2: confidence threshold < 0.55 → **never fired**. Measured table scores
        0.719/0.789/0.704 — indistinguishable from genuine numeric lookups. Retrieval score
        measures *topical relevance*, not which representation holds the answer.
  - [x] design 3: **prose-first**, numeric fallback → **PARTIALLY WORKS.** I called this a
        failure after seeing M01 alone; the full run then showed **M04 passing via
        `multi-doc(prose)`**. The design does fire and does work when doc-filtered prose
        retrieval surfaces the right chunk; M01/M03 fail because that retrieval returns
        `NOT_IN_CONTEXT` — a narrower, more fixable problem than "the design failed".
  - **CORRECTION:** I twice predicted failure from partial evidence, both times too
    pessimistically. Multi-doc is **1/4, not 0/4**. Recorded rather than quietly amended.
  - **DECISION: ships as a known weakness at 1/4 (0/1 held-out).** The remaining fix is
    doc-filtered prose retrieval, not arm selection.

### Rungs
- [x] **INT4** — full 20-question baseline: **11/20 (0.55)**; prose 6/8, numeric 4/8, multi-doc 1/4
- [x] **Four fixes attempted, measured, net zero** — see `results/fix_attempt_analysis.md`
  - [x] fix 1 previews carry all sections → `p12_t0` unretrieved → rank 1; **N04 fixed**
  - [x] fix 2 evidence gate on chosen cell → P04 stopped emitting `2,022`; fails honestly now
  - [x] fix 3 hybrid BM25+dense (RRF) → BM25 ranks P07's chunk first; **bottleneck moved to
        generation**, model had `64.2` in context and did not extract it
  - [x] fix 4 `diff` operand ordering → repaired the N06 sign flip
  - **Outcome: 11/20 → 11/20.** N04 fixed, N02 regressed. Table retrieval sits near a decision
    boundary where representation changes flip questions both ways.
- [x] **HELD-OUT evaluation** — `holdout_set.json`, 9 questions, 7 documents never inspected:
      **8/9 (0.889), prose 8/8 (1.00)**. Higher than the development set, not lower — the
      opposite of overfitting. See L0 in `results/known_limitations.md`.
- [x] **INT8** — attempted for real: **loads in 10.2 s, then Metal OOM on generation**.
      mlx-lm's own figures: 7,717 MB required vs 5,461 MB max (1.41x). Swap +2,944 MB.
      No accuracy figures reported — it produced no tokens.
- [x] **FP16** — ruled out by arithmetic (15.2 GB weights vs ~4.5 GB usable); will not be run
- [x] `results/quant_table.md` — explicit GB gap per rung, deployment recommendation
- [x] `results/multidoc_failure_analysis.md` — all 4 failures categorised
- [x] **Bottleneck located**: 7 of 9 failures are post-retrieval; earlier reranker
      recommendation corrected in `results/fix_attempt_analysis.md`

## Phase 6 — Memo & release `[~] MEMO DONE, RELEASE BLOCKED`

- [x] `MEMO.md` — all 5 required sections + reading-the-two-numbers; every figure traced
      to a measurement; 7 assistant errors disclosed
- [x] KV-cache napkin math computed (`results/kv_math.md`) — feeds memo §3
- [x] README with full run/test instructions
- [!] final commit + tag `stage-1` — **blocked: no GitHub remote configured**

## Key numbers so far

| metric | value |
|---|---|
| corpus | 16 docs, 713 pages, 119,077 cells |
| INT4 warm baseline | ~9 tok/s, 4.41 GB peak |
| MLX vs OS footprint gap | 0.31–0.68 GB (MLX under-reports) |
| `ps` RSS on Metal | **unusable** — ~50 MB vs 5.6 GB real |
| verification (1C) | P 0.500 / R 0.333 / exact 0.667 |
| QA gold set (dev) | **11/20 = 0.55** |
| QA held-out | **8/9 = 0.889**, prose **8/8** |
| routing (rules only) | 90% (was 60%) |
| multi-doc | 1/4 gold, 0/1 held-out |
| KV cache | 56 KB/token; **2 users** fit at 4k context |
| GPU OOM observed | yes — 7B INT4 + embedding model concurrently |
