# Stage 1 Memo — Trustworthy Local Document Intelligence (Apple M1, 8GB)

Corpus: 16 public statistical PDFs (FDIC, BEA ×3, Census ×3, Federal Reserve ×2, USDA ×2, OECD,
Treasury, World Bank, EPA, EIA), 713 pages → 119,077 table cells, 939 tables, 3,861 prose chunks.
Model: `mlx-community/Qwen2.5-7B-Instruct-4bit`, fully offline at runtime.

**Headline results up front, both labelled:**

| set | overall | prose | numeric | multi-doc | P50 |
|---|---|---|---|---|---|
| gold set (development, tuned against) | **11/20 = 0.55** | 6/8 | 4/8 | 1/4 | 99.7 s |
| held-out (7 documents never inspected) | **8/9 = 0.889** | 8/8 | **0 questions** | 0/1 | 29.3 s |

Verification layer (1C): precision **0.500**, recall 0.333, 3-way exact-match **0.667**, over 15
claims of which 6 are planted errors.

**Positive class, stated because precision/recall are meaningless without it:** *positive = the
claim is a planted error*, and the verifier *predicts positive when it returns `contradicted`*.
One planted error (claim 14, unsupported inference) has `unverifiable` as its **correct** verdict,
so answering it correctly scores as a false negative under this definition — which is why the
3-way exact-match figure is reported alongside, crediting every correct verdict. Full confusion
matrix in `results/verification_report.md`.

---

## 1. Chunking & retrieval

**Chosen.** Per-page, paragraph-aware chunks capped at 800 chars with 100-char overlap; chunks
never span a page boundary. Embeddings: `BAAI/bge-small-en-v1.5` (~130 MB) on MPS, FAISS
`IndexFlatIP` over normalised vectors. Retrieval k=5 prose chunks, k=3 candidate tables. Tables
are stored and retrieved **separately** from prose, keyed by a text "preview" of their section
banners, row labels and column headers — never by their numeric bodies, since "1,234" matches
nothing a user would type.

**Why chunks never cross pages.** Every prose answer must carry a `{doc, page}` citation. A chunk
spanning pages 12–13 forces the system to pick one page to cite, silently misattributing whichever
half fell on the other. The cost is less even chunk sizes; the benefit is that no citation is ever
a guess. **Rejected:** the standard whole-document sliding window, precisely because it breaks
per-page citation precision.

**k=3 tables, not 10–20 with a reranker.** On 8 GB the binding constraint is prompt size — each
rendered table costs context, and KV cache grows with it. A cross-encoder reranker would also add
a second model to a ~4.5 GB budget and confound the latency measurements. This turned out to be
the right call for an unexpected reason: **retrieval was not the bottleneck** (§2).

**Hybrid retrieval, added late.** Dense-only retrieval never surfaced FDIC page 1 for the
net-income question, though the chunk exists. A 384-dim embedding does not preserve the rare
tokens that pin a fact down ("FDIC-insured", "64.2"); BM25 ranks that exact chunk **first**. The
two are fused with Reciprocal Rank Fusion, chosen because BM25 scores and cosine similarities are
on incomparable scales and RRF consumes only rank order — no cross-calibration to fit.

---

## 2. Quantization damage — and where the ceiling actually is

### The ladder

| rung | weights + KV@4k | vs ~4.5 GB usable | vs MLX's stated 5.46 GB max | outcome |
|---|---|---|---|---|
| FP16 | 15.20 + 0.23 = **15.43 GB** | **−10.93 GB** | −9.97 GB | not run — see below |
| INT8 | 7.60 + 0.23 = **7.83 GB** | **−3.33 GB** | −2.37 GB | **loads, cannot generate** |
| INT4 | 3.80 + 0.23 = **4.03 GB** | **+0.47 GB** | +1.43 GB | working rung |

**FP16 was not attempted, deliberately.** The shortfall (10.93 GB) exceeds the entire machine.
No context, batch or KV setting closes a gap larger than physical memory, and downloading 15 GB to
watch it fail would add nothing the arithmetic does not already give.

**INT8 was attempted for real, and failed informatively.** It **loaded successfully in 10.2 s** —
macOS backed 7.6 GB of weights with swap rather than refusing — and then died during generation:

```
[WARNING] requires 7717 MB which is close to the maximum recommended size of 5461 MB
FAILED: RuntimeError: [METAL] Command buffer execution failed:
        Insufficient Memory (kIOGPUCommandBufferCallbackErrorOutOfMemory)
swap: 1008 MB → 3952 MB (delta +2944 MB, peaking 5767 MB mid-load)
```

*"Loads then dies"* is a stricter finding than "too big": weights being resident is not
sufficient, because the Metal command buffer needs headroom on top for activations and KV cache,
and there is none. `mlx-lm` quantified the overrun itself — **1.41×**. At failure the process held
8.12 GB (MLX) / 8.00 GB (footprint), essentially the whole machine. Corroborating evidence that
this ceiling is real: the identical Metal error appeared twice when the **INT4** model shared the
GPU with a 130 MB embedding model.

**No INT8 or FP16 accuracy figures appear anywhere in this project.** Neither produced a token.

### Where damage concentrates — and the honest limit on that claim

At INT4, numeric (0.50) sits below prose (0.75), matching the brief's expectation that cell-lookup
precision degrades first. Failures are overwhelmingly **column selection**: a real cell from the
correct row but the wrong column (N04 returned 0.46 against 498.5; N05 returned 0.54 against 0.91).

**This cannot be attributed to quantization.** With one runnable rung there is no comparison
point. These are *system* characteristics measured at INT4, not *precision-induced* ones. Claiming
"INT4 degrades numeric accuracy" would require the INT8 baseline we could not obtain.

### The finding that matters most: we were fixing the wrong layer

Two rounds of fixes — four in total — produced **zero net score movement (11/20 → 11/20)**, with a
one-for-one tradeoff (N04 fixed, N02 broke) and a **citation-rate regression from 1.00 to 0.90**.

Each fix did its mechanical job. Fix 1 took `p12_t0` from *unretrieved* to *rank 1*. Fix 3 put
`64.2` into the model's context for the first time. Both verifiably improved retrieval. Neither
moved the score.

We then measured, for every miss, whether the correct evidence was already in context at failure:

**Seven of nine failures are post-retrieval.** All four numeric misses had the correct cell shown
to the planner. M01 and M02 had their facts in doc-filtered context and the model returned
`NOT_IN_CONTEXT` anyway. Only M03 and H09 are genuine retrieval failures.

**This corrects an earlier conclusion of ours.** We had recommended a cross-encoder reranker. That
is wrong: a reranker reorders candidates retrieval already produced, and cannot help when the
right candidate is already ranked first and already in context. It would fix 2 of 9 failures. The
real bottleneck is **selection and extraction by a 7B model at INT4** — which on this hardware
cannot be addressed by a larger model (§2 arithmetic), making the accuracy ceiling partly a
*hardware* consequence rather than purely a design one.

### Multi-doc failure mechanism (previously undocumented)

| question | category | cause |
|---|---|---|
| M01 | **reasoning** | both facts in doc-filtered context; model returned `NOT_IN_CONTEXT` for both |
| M02 | **reasoning** | `65.6` and `11.5` both present; both declined — yet the same facts answer correctly as single-doc questions |
| M03 | **retrieval** | FDIC `64.2` absent from filtered context — the same defect as P07, so one bug behind two failures |
| H09 | **routing → retrieval** | router sent it to *prose* at confidence 0.3, bypassing the multi-doc path entirely; EPA `27.1` also absent |

**No case of aggregation failure.** The cross-document combination — the part one would assume is
hardest — was never the failure point. Every failure occurred *before* aggregation.

The two reasoning failures share a diagnosable cause: the multi-doc path puts the **full compound
question** ("Both X and Y describe… what does X report, and what does Y report?") to each document
separately, so the model sees a question half its context cannot answer and declines the whole
thing. Per-document decomposition is the fix, and it is plumbing — not retrieval, not model.

---

## 3. Napkin math — 50 concurrent users (KV cache)

From the model's own `config.json`, not estimated:

```
n_layers = 28,  n_kv_heads = 4 (GQA),  head_dim = 3584/28 = 128

KV bytes/token = 2 (K,V) × n_layers × n_kv_heads × head_dim × bytes_per_elem
               = 2 × 28 × 4 × 128 × 2
               = 57,344 bytes = 56 KB/token
```

**GQA is the number that matters.** Qwen2.5-7B has 4 KV heads, not 28 — each shared across 7 query
heads. Assuming multi-head attention would overstate KV memory by **7×**.

| context | KV per user | × 50 users |
|---|---|---|
| 2,048 | 0.12 GB | 5.9 GB |
| 4,096 | 0.23 GB | **11.7 GB** |
| 8,192 | 0.47 GB | 23.5 GB |

**Assumptions stated:** INT4 weights (4.0 GB, loaded once and shared — not per user), 4,096-token
context each, FP16 KV cache, no paging or eviction, single machine.

```
usable after macOS          ~4.5 GB
minus INT4 weights          −4.0 GB
remaining for KV             0.5 GB
KV per user @ 4k             0.23 GB
→ users that actually fit:   2
50 users would need:        11.7 GB KV + 4.0 GB weights = 15.7 GB  (~3.5× over budget)
```

**An 8 GB M1 is a single-digit-concurrency device.** Reaching 50 users means int8 KV quantization
(halves it), context far below 4k, vLLM-style block paging, or queueing so only ~2 sessions are
resident — realistically, a bigger machine or horizontal scaling. Not a tuning problem.

---

## 4. What verifies the verifier?

**Current state, stated plainly: it is not calibrated, and we can prove it.** Confidence is a
transparent product of retrieval score × path factor × penalty — deliberately *not* a model
self-report, since asking a 7B model its own confidence yields well-documented overconfidence.
But every input measures *how the answer was produced*, never whether it is right. Directly
observed: one answer scored **0.753 while wrong**; after the fix, the same question scored
**0.689 while right**. Confidence fell as correctness rose.

**Evidence the trust properties do hold**, from this build:

- **H09 declined rather than fabricated.** Asked to connect EPA vehicle fuel economy with USDA
  wheat exports — two unrelated sectors — the system returned *"Not answerable from the retrieved
  passages"* instead of inventing a link. It scores as a miss on accuracy while being exactly the
  correct trust behaviour. This is the single clearest piece of evidence for the property the
  whole evaluation is testing.
- **M03 refused to imply a comparison it could not make**, reporting *"Only one source could be
  used"* rather than presenting a one-sided answer as a two-document result.
- **The numeric path refuses rather than guesses** — missing cell, non-numeric cell, wrong arity,
  or a planner-invented cell all produce explicit refusals. Four separate silent-corruption paths
  were converted into loud, diagnosable failures this way.
- **Citation coverage was 1.00 on the gold-set baseline and on held-out** — every answer, right or
  wrong, carried a real citation. Note the corollary: citation coverage says nothing about
  correctness, and should not be read as a quality signal.

**How we would actually verify the verifier.** (i) Seeded errors we did not write — our planted
errors were authored by the same person who built the checker, so they test the mechanism but not
its blind spots. (ii) Calibration: bin predictions by confidence and plot observed accuracy per
bin; we have the data to do this and have not, so we make no calibration claim. (iii) Agreement
checks between the numeric recompute path and the text path on the same claim — where they
disagree is where the verifier is weakest. (iv) The held-out discipline applied to claims, not
just questions.

**One prediction we recorded and got wrong:** the answer key predicted claim 10 (unit error) would
be missed, since units live in section banners rather than cells. The recompute path did decline —
but the *text* path caught it, because the retrieved prose carried the "(in billions)" banner the
cell record lacks. Redundancy between paths covered a gap either alone would have missed. An
earlier run also scored that claim correct for an entirely bogus reason (it compared 0.0 against
498.5) — a right verdict from a broken mechanism, which only reading per-claim reasoning exposed.

---

## 5. Reading the two accuracy numbers

**The held-out set contains zero numeric questions** — 8 prose + 1 multi-doc. This is the primary
explanation for 0.55 → 0.889 and it must lead: the held-out set omits the question type the system
scores worst on. It is not a like-for-like comparison and not evidence of better general
capability.

A secondary effect also holds: the gold set's numeric block is **100% FDIC** multi-section tables,
the corpus's hardest extraction target — the only document whose stacked tables survived
extraction cleanly enough to key ground truth against, and only after a dedicated label-loss
repair pass. We could not write held-out numeric questions at all, because table extraction on the
other seven documents is too corrupted to serve as ground truth (row labels like `'Billion $53'`,
values like `'024.'`).

What held-out *does* legitimately support: **8/8 observed on held-out prose, consistent with the
gold-set prose rate, with no evidence of degradation on unseen documents.** With n=8 that is not a
stable 100% accuracy claim and we do not report it as one. What it rules out is overfitting — had
the gold-set number been inflated by our having read those documents while debugging, held-out
would have scored lower, not higher.

---

## 6. AI disclosure

Assistant: **Claude Opus 5** (exact model identifier `claude-opus-5`), used via the Claude Code
CLI. Used throughout — corpus selection and URL
verification, all ingestion/QA/verification/benchmark code, the gold set and planted errors, and
drafting these results documents. Full running log in `AI_LOG.md`.

Things it got wrong during this build, corrected in place:

- **Misdiagnosed a defect and stated it confidently.** Claimed an entire FDIC table section had
  been "silently dropped by extraction". Wrong — the data was present the whole time at
  `p12_t0 r17c1 = 0.6`, in a row whose *label* had been dropped. Label loss, not data loss; the
  two need different fixes.
- **Predicted accuracy gains three times and delivered none.** Projected 17–18/20 after the first
  fixes, revised to 12–15/20, delivered 11/20 — unchanged. The first projection wrongly treated
  "the right cell is now retrievable" as equivalent to "the right cell will be selected".
- **Recommended a reranker as the next investment.** Later measurement showed 7 of 9 failures are
  post-retrieval, where a reranker cannot help. Corrected in `fix_attempt_analysis.md`.
- **Declared multi-doc design 3 a failure from one data point.** M04 then passed via that exact
  path; multi-doc is 1/4, not 0/4.
- **Caused a GPU OOM twice by running embedding work while a benchmark held the model**, after
  explicitly stating it would not do that again. It contaminated one measurement, and the 494 s
  latency outlier from that period is treated as suspect.
- **Shipped a broken verifier in the first run** (precision 0.300, 10 of 15 claims contradicted, 7
  wrongly) by comparing claims against the *first* number in a sentence — so "poverty rate in
  2022 was 11.5 percent" was checked against the year **2022**. Fixed to 0.500, not shipped as a
  "limitation".
- **Left a `.gitignore` bug that would have committed the plaintext answer key.** `.gitignore` has
  no trailing-comment syntax, so the line `answer_key.json  # NEVER commit plaintext key` matched
  nothing. `git check-ignore` confirmed both the key and the Fernet secret were committable.

The recurring pattern in these is over-confident inference from partial evidence, caught by
measuring rather than assuming. The most valuable results in this memo — the post-retrieval
bottleneck, the multi-doc categorisation, the INT8 wall — all came from checking a belief against
data that could have contradicted it.
