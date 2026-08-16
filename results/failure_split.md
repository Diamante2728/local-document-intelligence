# Multi-doc failure split — what LoRA can and cannot fix

Phase 2A Step 1. Formal write-up of the retrieval-vs-reasoning split across every known multi-doc
failure, sourced from the Stage 1 closeout artifacts (`results/multidoc_failure_analysis.md`,
`results/fix_attempt_analysis.md`).

**This determines what the fine-tune is allowed to target.** LoRA adjusts model weights: it can
change how a model reasons over the context it is handed. It cannot change *which documents reach
that context*. Training against retrieval-layer failures would be training against a defect the
method structurally cannot fix.

## The split

| case | mechanism | LoRA-trainable | why |
|---|---|---|---|
| **M01** | reasoning | **yes** | both facts present in doc-filtered context; model returned `NOT_IN_CONTEXT` for both |
| **M02** | reasoning | **yes** | `65.6` and `11.5` both present; both declined — yet the same facts answer correctly as single-document questions |
| **M03** | retrieval | no | FDIC `64.2` **absent** from the filtered context; the BEA half was fine |
| **H09** | routing → retrieval | no | router sent it to the *prose* path at confidence 0.3, bypassing multi-doc entirely; EPA `27.1` also absent |
| *M04* | *(passed)* | — | answered correctly via `multi-doc(prose, single-source)` |

**2 trainable, 2 not.** An even split, not a dominance either way.

## Case detail

### M01 — reasoning (trainable)
*"Both the BEA GDP release and the Federal Reserve Monetary Policy Report describe U.S. economic
conditions in early 2024. What GDP growth rate does BEA report for Q1 2024, and what federal funds
rate target range does the Fed report holding?"*

Routed correctly to multi-doc (confidence 0.85). Returned **"No source document could answer this
question."**

The corpus-wide view is misleading here and nearly produced a wrong diagnosis. Unfiltered
retrieval returns `fed_monetary_policy_report` in all five prose slots and never surfaces
`bea_gdp` — which looks like retrieval failure. But the multi-doc path re-retrieves **per
document**, and under that filter both facts are present: `1.3` from BEA, the rate range from the
Fed. The model was shown the right passages, one document at a time, and declined both.

### M02 — reasoning (trainable)
*"Compare the reported U.S. homeownership rate from the Census housing release with the official
poverty rate from the Census poverty report."*

Cleanest case in the set. Both documents reachable, both facts in doc-filtered context (`65.6`,
`11.5`), both stated in plain narrative sentences. **Both figures are answered correctly elsewhere
in the gold set as single-document prose questions (P02, P04).** The model has demonstrably read
these sentences successfully in another framing and failed here.

### M03 — retrieval (NOT trainable)
FDIC `64.2` is absent from the five chunks the per-document filter returns. Same chunk the system
fails to retrieve for **P07**, the standalone FDIC net-income question, which also misses — one
defect behind two failures. No weight update fixes a chunk that never arrives.

### H09 — routing → retrieval (NOT trainable)
Never reached the multi-doc path: the rules-only router classified it **prose** at its lowest
confidence band (0.3). EPA `27.1` was also absent from filtered context. Two defects stacked,
neither in the model's reasoning.

## What this implies for the training target

**Train only the M01/M02 pattern:** the right documents reach context and the model fails to
combine facts across them. Both share a diagnosable cause identified in Stage 1 — the multi-doc
path puts the **full compound question** ("Both X and Y describe… what does X report, and what
does Y report?") to each document separately, so the model sees a question half its context cannot
answer and returns `NOT_IN_CONTEXT` for the whole thing.

That is a *behavioural* failure under a specific prompt shape, which is exactly what LoRA can
move. Training data must therefore teach: **given one document's context and a compound
cross-document question, answer the part this document supports and do not decline the whole.**

## The honest caveat this creates for 2C(iii)

Half the known multi-doc failures are out of scope for fine-tuning by construction. Even a
perfectly successful fine-tune cannot lift multi-doc past the ceiling imposed by M03/H09-class
retrieval defects. When 2C(iii) asks whether fine-tuning was the right tool, this split is
half the answer before any training has run — and it was known in advance, not discovered
afterwards.

There is a second consideration worth stating plainly: the Stage 1 diagnosis says the compound-
question prompt shape is the proximate cause, and **that is fixable by decomposing the question
per document — a plumbing change, not a model change.** Fine-tuning is being asked to compensate
for a prompt-construction problem. Whether that is the right engineering call is precisely what
2C(iii) must adjudicate, using the prompted-only baseline as the comparison.

---

# Appendix — training-set sampling against the M01/M02 pattern

Data only, recorded during the Stage 2 verification pass. No conclusions drawn here.

## Method

Random sample (seed 2026) of 20 from the 689 examples in `data/train_multidoc.jsonl`.

Classified MATCH when all of: context contains exactly ONE document, question is compound,
target answers the supported half and contains the recorded figure. Classified NEGATIVE when
`kind == "negative"` and the target is the literal string `NOT_IN_CONTEXT`.

## Result

```
MATCH (single-doc context, compound question, partial answer)   13/20
NEGATIVE (target is NOT_IN_CONTEXT)                              7/20
neither                                                          0/20
```

Sample kind distribution: `second` 10, `negative` 7, `first` 3.
Full-set kind distribution: `second` 263, `first` 260, `negative` 166 (n=689).

All 20 sampled examples had exactly one document in context. None presented two documents.

## The 7 NEGATIVE examples in the sample, verbatim

```
 8. op=aggregation
    Q: Add together space administration science from the Treasury monthly statement and
       valuation capital consumption adjustments from the BEA GDP release.
    A: NOT_IN_CONTEXT

10. op=contradiction
    Q: Check the OECD Economic Outlook annex against the Census poverty report: state rest
       world world and der aged older, and flag any discrepancy.
    A: NOT_IN_CONTEXT

11. op=lookup_then_combine
    Q: Look up dap urea exports china (the World Bank commodity markets outlook) and fourth
       quarter downward revision (the BEA GDP release). Present the two values side by side.
    A: NOT_IN_CONTEXT

12. op=lookup_then_combine
    Q: I need two numbers: copper lme grade minimum from the World Bank commodity markets
       outlook, and rates chain-type price indexes from the BEA personal income report.
    A: NOT_IN_CONTEXT

14. op=contradiction
    Q: Do the Census FT-900 trade release and the Federal Reserve Monetary Policy Report agree?
       Give gem diamonds from the first and urban economics vol from the second...
    A: NOT_IN_CONTEXT

15. op=lookup_then_combine
    Q: First find efficiency measured kilowatt hours in the EPA automotive trends summary, then
       find office balance payments division in the Census FT-900 trade release...
    A: NOT_IN_CONTEXT

19. op=aggregation
    Q: Add together liability basis table line from the BEA international transactions release
       and ual income median from the Fed Survey of Consumer Finances...
    A: NOT_IN_CONTEXT
```

## Observed topic-phrase quality in the NEGATIVE sample

Topic phrases extracted from source text in the above: `rest world world`, `der aged older`,
`ual income median`, `office balance payments division`, `liability basis table line`,
`rates chain-type price indexes`, `dap urea exports china`.

## Coverage note

`kind` values present in the generator: `first`, `second`, `negative`. Counts over all 689:
`first` 260, `second` 263, `negative` 166. No `kind` exists for a single document supporting
both halves of the compound question.
