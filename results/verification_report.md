# Verification Report (Deliverable 1C)

Verification of the 15 claims in `summary.md` against the 16-document corpus, scored against the decrypted `answer_key.enc`.

## Positive class (stated, because precision/recall are meaningless without it)

- **positive** = the claim is a planted error
- the verifier **predicts positive** when it returns `contradicted`

One planted error (claim 14, unsupported inference) has `unverifiable` as its *correct* verdict. Under this positive class, answering it correctly scores as a false negative. That tension is real and is reported rather than defined away — see `verdict_exact_match` below for the metric that credits every correct verdict.

## Headline numbers

- **Precision** 0.500  (TP 2 / TP+FP 4)
- **Recall** 0.333  (TP 2 / TP+FN 6)
- **F1** 0.400
- **Verdict exact-match accuracy** 0.667 (all three verdicts credited)

TP 2 · FP 2 · FN 4 · TN 7

## 3-way confusion matrix (rows = truth, cols = predicted)

| truth \ predicted | supported | contradicted | unverifiable |
|---|---|---|---|
| **supported** | 7 | 2 | 0 |
| **contradicted** | 3 | 2 | 0 |
| **unverifiable** | 0 | 0 | 1 |

Verdicts actually produced: ['contradicted', 'supported', 'unverifiable'] — all three are reachable.

## Per-claim results

| # | expected | predicted | ok | planted error type | conf | basis |
|---|---|---|---|---|---|---|
| 1 | supported | supported | ✅ | — | 0.85 | The excerpt directly states the same rate of increase for th |
| 2 | supported | contradicted | ❌ | — | 0.8 | The excerpts state that personal income increased $114.1 bil |
| 3 | supported | supported | ✅ | — | 0.85 | The evidence directly states the same figures for the U.S. c |
| 4 | supported | supported | ✅ | — | 0.85 | The evidence directly states the increase in net income and  |
| 5 | supported | supported | ✅ | — | 0.85 | The excerpts state the exact number of institutions reportin |
| 6 | contradicted | contradicted | ✅ | wrong number | 0.85 | recomputed 0.6 does not match claimed 0.85 |
| 7 | supported | supported | ✅ | — | 0.9 | recomputed value matches the claim |
| 8 | supported | supported | ✅ | — | 0.9 | recomputed value matches the claim |
| 9 | supported | contradicted | ❌ | — | 0.8 | The excerpts show the total loans and leases outstanding at  |
| 10 | contradicted | contradicted | ✅ | unit error | 0.8 | The excerpts show that construction and development loans ou |
| 11 | contradicted | supported | ❌ | right number, wrong period | 0.85 | The excerpt states that the homeownership rate was 65.6 perc |
| 12 | supported | supported | ✅ | — | 0.85 | The excerpts provide the exact figures stated in the claim. |
| 13 | contradicted | supported | ❌ | misattribution | 0.85 | The excerpts confirm the Federal Open Market Committee has m |
| 14 | unverifiable | unverifiable | ✅ | unsupported inference | 0.753 | The excerpts do not provide a comparison between the noncurr |
| 15 | contradicted | supported | ❌ | cross-document contradiction | 0.85 | The excerpts provide the exact values for Brent crude oil sp |

## Honest failure analysis

Ten of fifteen verdicts are correct. The five failures are more informative than the successes,
and they fall into three distinct mechanisms.

### Miss 1 — a right number silences the qualifier around it (claims 11 and 13)

Both planted errors attach a **correct number to a wrong frame**, and both slipped through as
`supported`.

- Claim 11 (right number, wrong period): the verifier's stated reason was
  *"The excerpt states that the homeownership rate was 65.6 percent in the fourth quarter of
  2023."* The source says **first quarter 2024**; the same page gives Q4 2023 as **65.7**. The
  model echoed the claim's own period back as though it had read it in the evidence.
- Claim 13 (misattribution): reason was *"The excerpts confirm the Federal Open Market Committee
  has maintained the target range ... since its July 2023 meeting."* True — and completely
  silent on the claim's assertion that **the Bureau of Economic Analysis** reports it.

**Mechanism.** Verification is anchored on the numeric fact. Once the number matches retrieved
text, the surrounding qualifiers — period, attribution, unit — are treated as restatement rather
than as separate assertions to be checked. The system prompt explicitly instructs the model to
check period and organisation; it still anchored on the number. This is not fixable by asking
more firmly: the qualifier needs to be extracted as its own checkable proposition and verified
independently, which the current design does not do.

### Miss 2 — a contradiction *between* two facts is invisible to per-excerpt checking (claim 15)

Claim 15 welds a narrative spot price ($68/b in April) to a forecast-table figure (13.2 Mb/d) as
if they described one period. The verifier's reason: *"The excerpts provide the exact values for
Brent crude oil spot price and U.S. crude oil production as stated in the claim."* Both halves
are individually true, so per-excerpt verification confirms each and reports `supported`.

**Mechanism.** Evidence is gathered and judged **per claim**, not per proposition-pair. A
cross-source or cross-period contradiction lives in the *relationship* between two facts; nothing
in the pipeline ever puts the two retrieved passages in tension with each other. Catching this
class requires decomposing the claim into propositions and checking them for mutual consistency —
a different architecture, not a better prompt.

### Miss 3 — over-literal small-model judgements produce false contradictions (claims 2 and 9)

The two false positives are the verifier being wrong in the *unsafe* direction: calling a true
claim false.

- Claim 2: the reason is self-refuting — *"the claim states $114.1 billion, which is correct, but
  the claim incorrectly states the increase as 0.5 percent at a monthly rate, while the excerpts
  state it as 0.5 percent."* It manufactured a distinction between "0.5 percent at a monthly
  rate" and "0.5 percent".
- Claim 9: *"The excerpts show the total loans and leases outstanding ... as $1,868.0 billion,
  not $12,419.3 billion."* It read a different row out of the retrieved text.

**Mechanism.** When the numeric recompute declines (correctly — it could not tie either claim to
a single cell unambiguously), the fallback is a 7B model reading prose. At INT4 it is prone both
to over-literal contrast and to picking the wrong figure out of a dense table rendered as text.
These are the claims where a stronger recompute path, not a stronger prompt, would help.

### A prediction in the answer key that turned out wrong

`answer_key.json` records claim 10 (unit error) as an **expected miss**, on the reasoning that
units live in the section banner rather than in the cell, so a magnitude-only recompute would see
498.5 == 498.5 and call it supported. That reasoning is correct **about the recompute path** — and
the recompute path did decline this claim. But the text path caught it outright:
*"construction and development loans outstanding totalled $498.5 billion, not $498.5 million."*
The retrieved prose excerpt carried the "(in billions)" banner that the cell record lacks.

Two things worth stating plainly. First, the prediction was wrong, and the reason it was wrong is
that redundancy between the two verification paths covered a gap that either path alone would have
missed. Second, an earlier run *also* scored claim 10 as `contradicted`, but for a bogus reason —
it had matched an unrelated cell and compared 0.0 against 498.5. That was a correct verdict from a
broken mechanism, and it would have been reported as a success had the per-claim basis strings not
been read individually. Headline metrics would not have shown it.

### What this says about the metrics

Precision and recall move in opposite directions across the two runs (precision 0.300 -> 0.500,
recall 0.500 -> 0.333) because the first run's recall was inflated by indiscriminate
`contradicted` verdicts — it "caught" planted errors by contradicting nearly everything. Recall
alone would have rated the broken version as better. That is the strongest practical argument in
this report for stating the positive class and reporting precision, recall and exact-match
together rather than any one of them.

## Claim text

1. Real gross domestic product increased at an annual rate of 1.3 percent in the first quarter of 2024, according to BEA's second estimate.
2. Personal income increased $114.1 billion in May, a rise of 0.5 percent at a monthly rate.
3. The U.S. current-account deficit widened by $15.9 billion, or 7.2 percent, in the first quarter of 2024.
4. Aggregate net income for FDIC-insured commercial banks and savings institutions rose to $64.2 billion in the first quarter of 2024, an increase of $28.4 billion, or 79.5 percent, from the previous quarter.
5. That first-quarter banking result covers 4,568 FDIC-insured commercial banks and savings institutions.
6. The noncurrent loan rate for construction and development loans at all insured institutions was 0.85 percent.
7. Credit card loans carried a noncurrent rate of 1.80 percent at all insured institutions, the highest of any loan category shown in the FDIC loan-performance table.
8. The net charge-off rate for credit card loans at all insured institutions was 4.70 percent year to date.
9. Total loans and leases outstanding at all insured institutions stood at $12,419.3 billion.
10. Construction and development loans outstanding at all insured institutions totalled $498.5 million.
11. The U.S. homeownership rate was 65.6 percent in the fourth quarter of 2023.
12. The official poverty rate in 2022 was 11.5 percent, with 37.9 million people in poverty.
13. The Bureau of Economic Analysis reports that the Federal Open Market Committee has maintained the federal funds rate at 5-1/4 to 5-1/2 percent since its July 2023 meeting.
14. Because the noncurrent rate for construction and development loans is well below the credit card rate, commercial real estate lending presents no material risk to the banking system in the coming year.
15. The Brent crude oil spot price averaged $68 per barrel in April, and U.S. crude oil production is projected at 13.2 million barrels per day.
