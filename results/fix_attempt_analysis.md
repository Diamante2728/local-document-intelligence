# Fix Attempt Analysis — four fixes, zero net gain

Recorded because a null result that is well understood is worth more than a score bump that is not, and because I predicted gains three times and delivered none.

## Headline

| metric | baseline | after 4 fixes |
|---|---|---|
| overall accuracy | 0.55 | 0.55 |
| citation rate | 1.0 | 0.9 |
| P50 latency (s) | 89.3 | 99.68 |
| P95 latency (s) | 180.68 | 243.98 |
| prose | 6/8 | 6/8 |
| numeric | 4/8 | 4/8 |
| multi-doc | 1/4 | 1/4 |

**11/20 -> 11/20. Citation rate fell 1.00 -> 0.90.**

## Per-question movement

| id | baseline | after | moved | baseline path | after path |
|---|---|---|---|---|---|
| M01 | MISS | MISS |  | multi-doc(numeric) | multi-doc |
| M02 | MISS | MISS |  | multi-doc(numeric) | multi-doc |
| M03 | MISS | MISS |  | multi-doc(numeric, single-source) | multi-doc(numeric, single-source) |
| M04 | OK | OK |  | multi-doc(prose) | multi-doc(prose, single-source) |
| N01 | OK | OK |  | numeric | numeric |
| N02 | OK | MISS | **REGRESSED** | numeric | numeric->prose |
| N03 | MISS | MISS |  | numeric->prose | numeric->prose |
| N04 | MISS | OK | **FIXED** | numeric | numeric |
| N05 | MISS | MISS |  | numeric->prose | numeric |
| N06 | OK | OK |  | numeric | numeric |
| N07 | OK | OK |  | numeric | numeric |
| N08 | MISS | MISS |  | numeric | numeric->prose |
| P01 | OK | OK |  | prose | prose |
| P02 | OK | OK |  | numeric->prose | numeric->prose |
| P03 | OK | OK |  | prose | prose |
| P04 | MISS | MISS |  | numeric | numeric->prose |
| P05 | OK | OK |  | prose | prose |
| P06 | OK | OK |  | prose | prose |
| P07 | MISS | MISS |  | prose | prose |
| P08 | OK | OK |  | prose | prose |

## What each fix actually did

Every fix performed its mechanical function. None converted into score.

**Fix 1 — table previews carry all section headers.** Verified directly: `p12_t0` (FDIC Table
V-A) went from *not retrieved at all* to rank 1 for the questions that need it, and **N04 was
fixed** (baseline returned 0.46 against an expected 498.5). But previews changed for all 260
retrievable tables, which reshuffled ranking globally and **broke N02**, a question that had been
passing in both prior runs. A clean one-for-one trade.

**Fix 2 — evidence gate on the planner's chosen cell.** Worked as designed: P04 stopped returning
`2,022` (a year, previously emitted at confidence 0.726) and routed to prose instead. The system
now fails *honestly* on that question rather than confidently wrong. Same score, better behaviour.

**Fix 3 — hybrid BM25 + dense retrieval, RRF-fused.** Worked at the retrieval layer and was
verified end-to-end: BM25 ranks P07's answer chunk (FDIC p1) **first** where dense retrieval never
surfaced it, and `'64.2'` demonstrably reaches the model's context. The model then failed to
extract it. **The bottleneck moved from retrieval to generation** — which is a real finding, just
not a scoring one.

**Fix 4 — `diff` operand ordering.** The only unambiguous win. Fixes 1+2 had regressed N06 to
`-1.2` (sign flip: it computed 0.60 - 1.80). My prompt said operands were "ordered [first,
second]" without defining "first" for a comparative question. Clarifying it restored N06.

## The finding that matters

**Table retrieval on this corpus sits near a decision boundary.** Small changes in how a table is
represented flip questions in *both* directions at roughly equal rates. Across two runs the fixes
produced: N04 fixed / N02 regressed / N06 regressed then repaired. That is the signature of
retrieval operating at the edge of its discriminative power, not of a specific bug.

The mechanism is visible in the data: ~940 extracted tables from statistical PDFs produce preview
strings that are highly similar to one another (same institution names, same column vocabulary,
same reporting periods), and a 384-dimension embedding cannot separate them reliably. Retrieval
scores for competing tables cluster within ~0.02 of each other — well inside the range that a
representation change can invert.

**Implication:** reaching 0.85 is unlikely to come from further tuning of this design. It needs a
structural change — a cross-encoder reranker over candidate tables, or table-level metadata
captured at ingestion rather than reconstructed from noisy extraction. Both were rejected earlier
on this hardware for defensible reasons (a reranker is a second model on a ~4.5 GB budget), which
means the accuracy ceiling here is partly a *hardware* consequence, not only a design one.

## Honest note on prediction

I projected 17-18/20 after measuring that the correct cells had become visible to the planner,
then revised to 12-15/20, and delivered 11/20. The error in the first projection was treating
"the right cell is now retrievable" as equivalent to "the right cell will be selected". N05 and
N06 both disprove that: visibility is necessary, not sufficient.

