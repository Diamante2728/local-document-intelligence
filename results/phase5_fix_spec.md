# Phase 5 — pre-benchmark fix spec

Two defects must be fixed **before** the INT4 baseline is re-run. Neither is a quantization
effect, so measuring them would put noise into the one comparison the ladder exists to make.

Written before implementing, so the acceptance criteria are fixed in advance rather than
adjusted to match whatever the code ends up doing.

---

## Why fix first (the sequencing argument)

- **Multi-doc scored 0/4.** The cause is structural, not precision-related: `answer_multidoc()`
  has no prose mode. Re-running INT4 unchanged reproduces 0/4 after ~40 minutes.
- **The harness lost a 19/20 run.** Results are written only at the end. The run was killed by
  session teardown at question 19 and nothing survived. On a machine that thrashes (see
  Environment below), interruption is likely, not exceptional.
- A ladder rung is only worth measuring once the thing being measured is the model, not the
  scaffolding around it.

---

## FIX 1 — Incremental checkpointing in `src/quant/bench.py`

### Problem
`run_bench()` accumulates rows in memory and writes `results/bench_<label>.json` once, after the
final question. A 40-minute run that dies at 19/20 yields nothing.

### Required behaviour
1. After **each** question completes, append its row to
   `results/bench_<label>.partial.jsonl` (one JSON object per line, flushed immediately).
2. Add `--resume`: on start, read the partial file, skip any question `id` already present, and
   continue. Resumed rows must be indistinguishable from freshly computed ones in the final
   summary.
3. On successful completion write the aggregate `results/bench_<label>.json` as now, and leave
   the `.jsonl` in place as the audit trail.
4. `--fresh` forces a restart, ignoring and truncating any partial file.

### Acceptance criteria
- Kill a run mid-way (`--limit 4`, interrupt after 2). The `.jsonl` holds exactly the completed
  rows, each valid JSON.
- Re-run with `--resume`: it skips the completed ids, prints which it skipped, and the final
  summary covers all 4 questions.
- A completed run produces a `bench_<label>.json` byte-identical in structure to today's.

### Explicitly out of scope
Do not change grading, routing, or any measurement. This fix must not alter a single verdict —
it only changes when results reach disk.

---

## FIX 2 — Prose support in the multi-doc path (`src/qa/answer.py`)

### Problem
`answer_multidoc()` calls `answer_numeric()` once per candidate document and returns
"Could not compute a comparable figure from two documents" unless **both** yield a number. Three
of the four gold multi-doc questions have answers that live in prose:

| id | asks for | lives in |
|---|---|---|
| M01 | GDP growth rate + federal funds target range | prose, prose |
| M02 | homeownership rate + poverty rate | prose, prose |
| M03 | net income + current-account deficit change | prose, prose |
| M04 | Brent spot price | prose |

So the path cannot answer them by construction. Observed: M01/M03 returned the "could not
compute" refusal; M02 returned a doc id.

### Required behaviour
1. Attempt the numeric sub-answer per document as today.
2. Where a document yields no numeric value, fall back to a **prose** sub-answer restricted to
   that document (retrieval filtered by `doc_id`).
3. Compose the final answer from whichever sub-answers succeeded, citing **each** source
   document separately (constraint #3 — multi-doc answers must cite every source used).
4. Return `unverifiable`-style honesty when fewer than two documents contribute: say plainly
   that only one source could be used, rather than implying a comparison was made.
5. `path_taken` must record what actually happened — e.g. `multi-doc(numeric+prose)` — so a
   transcript never overstates the method.

### Required supporting change
`answer_prose()` needs an optional `doc_ids` filter so a sub-answer can be confined to one
document. Retrieval must over-fetch before filtering so the filter does not starve results
(the same pattern already used in `search_tables`).

### Acceptance criteria
- M01, M02, M03 each return an answer containing the expected figures from `gold_set.json`.
- Every returned multi-doc answer cites **≥2 distinct `doc` values** when two sources
  contributed.
- A question whose second document genuinely has nothing must still say so rather than
  fabricating a comparison — verified by asserting the refusal wording is preserved for a
  deliberately unanswerable multi-doc question.
- No regression on prose/numeric paths: `--type prose` and `--type numeric` scores must not fall.

### Explicitly out of scope
Do not relax grading in `bench.py` to make multi-doc pass. If a question still fails after the
fix, it fails and is reported.

---

## Caveats to carry into `results/quant_table.md` (do not quietly drop)

1. **The measurement environment is not clean.** During the aborted INT4 run, M02 took **494 s**
   against a ~90 s median, and `pgrep` itself failed with *"sysmond service not found"* — the
   machine was thrashing hard enough to degrade OS services. macOS subsequently resized swap
   from 10 GB to 2 GB. **P95 latency on this machine measures swap behaviour, not model speed**,
   and must be labelled as such rather than presented as a model characteristic. Report P50 and
   P95 with the swap delta beside them.

2. **`ps` RSS is unusable on Metal.** Measured ~50 MB RSS against ~5.6 GB `footprint` for the
   same loaded model, because Metal's unified-memory buffers are not counted in RSS. Report
   `mx.get_peak_memory()` **and** `footprint`; the observed gap was ~0.3 GB (MLX under-reporting),
   not the ~2x the build spec warned about — state the measured figure, not the expected one.

3. **Numeric failures concentrate in column selection.** N04 (`0.46` vs `498.5`) and N05
   (`0.54` vs `0.91`) returned real cells from the **correct row, wrong column** — an adjacent
   institution-size bucket instead of "All Insured Institutions". N08 was a wrong row. N03
   refused rather than guessed, which is the designed behaviour.
   **This must not be attributed to INT4** until a second rung exists to compare against. With
   one rung it is a property of the *system*, not of the *precision*.

4. **The INT8 artifact is pre-quantized, not locally converted.** `mlx-community/
   Qwen2.5-7B-Instruct-8bit` reports `group_size=64`, matching the 4-bit exactly, with the same
   28 layers / 4 KV heads — so it is genuinely the same model at two precisions. Local
   conversion would need ~23 GB against ~30 GB free on an already-swapping disk. State the
   deviation; do not claim "I converted these".

5. **FP16 is ruled out by arithmetic, not by a failed run** (15.2 GB weights vs ~4.5 GB usable).
   No FP16 latency or accuracy numbers may appear in the table — an empty, explained row is
   correct; a fabricated one is not.

---

## Sequence after these fixes

3. Re-run INT4 baseline (`--fresh`), full 20 questions, with checkpointing active.
4. Fetch the 8-bit artifact, then `python -m src.quant.ladder try-int8` — record whatever
   happens (load, swap storm, OOM) verbatim as the result.
5. Write `results/quant_table.md`: per-type accuracy, P50/P95, peak memory for INT4; observed
   behaviour for INT8; arithmetic for FP16; plus a deployment recommendation.
