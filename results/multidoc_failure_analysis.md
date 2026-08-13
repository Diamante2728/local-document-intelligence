# Multi-doc Failure Analysis

Multi-doc is the weakest path in the system: **1/4 on the gold set, 0/1 held-out**. Until now it
had no documented failure mechanism anywhere in the results — only the observation that it
scored badly. This document fixes that by reading every failing question by hand and classifying
it against evidence.

## Method

Each failing question is classified into exactly one of:

- **(a) RETRIEVAL** — the right document(s) never reached the model's context
- **(b) REASONING** — the right context reached the model, and it failed to produce the answer
- **(c) AGGREGATION** — both facts reached the model and were individually correct, but the
  cross-document comparison/computation itself was wrong

The evidence is the **per-document filtered retrieval** the multi-doc path actually performs.
`answer_multidoc` selects candidate documents, then answers each one *separately* with retrieval
confined to that `doc_id`. So the question that decides (a) vs (b) is not "did the corpus-wide
search find the document" but "did the **doc-filtered** search put the needed fact in context".
Both were measured; they differ, and the distinction matters.

| question | doc | fact | in doc-filtered context? |
|---|---|---|---|
| M01 | `bea_gdp_2024q1_second_estimate` | `1.3` | **YES** |
| M01 | `fed_monetary_policy_report_2024_03` | `5` (rate range) | **YES** |
| M02 | `census_housing_vacancies` | `65.6` | **YES** |
| M02 | `census_poverty_2022_p60_280` | `11.5` | **YES** |
| M03 | `fdic_quarterly_banking_profile_2024q1` | `64.2` | **NO** |
| M03 | `bea_international_transactions_2024q1` | `15.9` | **YES** |
| H09 | `epa_automotive_trends_2024_exec_summary` | `27.1` | **NO** |
| H09 | `usda_wasde_2026_06` | `775` | **YES** |

---

## M01 — category (b) REASONING

*"Both the BEA GDP release and the Federal Reserve Monetary Policy Report describe U.S. economic
conditions in early 2024. What GDP growth rate does BEA report for Q1 2024, and what federal
funds rate target range does the Fed report holding?"*

Routed correctly to multi-doc (confidence 0.85). Returned **"No source document could answer this
question."**

This is **not** a retrieval failure, and the corpus-wide view is misleading here. Unfiltered
retrieval returns `fed_monetary_policy_report` in all five prose slots and never surfaces
`bea_gdp` — which looks like category (a). But the multi-doc path does not use the unfiltered
result: it re-retrieves *per document*, and under that filter **both facts are present in
context** — `1.3` from the BEA release and the rate range from the Fed report.

So the model was shown the right passages for both documents and returned `NOT_IN_CONTEXT` for
both, which is what drives the "No source document could answer" wording. The evidence was there
and was not used. Category **(b)**.

*Caveat on this one:* the needle `5` for the Fed half is weak (it matches many strings), so the
Fed side of the evidence is softer than the BEA side. The BEA half — `1.3` present, unused — is
solid on its own and is enough to establish (b).

---

## M02 — category (b) REASONING

*"Compare the reported U.S. homeownership rate from the Census housing release with the official
poverty rate from the Census poverty report."*

Routed correctly (0.85). Returned **"No source document could answer this question."**

The cleanest case in the set. Corpus-wide retrieval reaches **both** wanted documents, and
doc-filtered retrieval puts **both** facts in context — `65.6` from the housing release, `11.5`
from the poverty report. Both are short, unambiguous figures stated in plain narrative sentences
on page 1 and page 8 respectively; both were answered correctly as *single-document* prose
questions elsewhere in the gold set (P02 and P04 use the same underlying facts).

The model had each fact in front of it, one document at a time, and declined both. Category
**(b)**, with no retrieval excuse available.

---

## M03 — category (a) RETRIEVAL (partial)

*"The FDIC Quarterly Banking Profile and the BEA international transactions release both report
dollar changes for early 2024. What was FDIC-insured aggregate net income, and by how much did
the current-account deficit widen?"*

Routed correctly (0.85). Returned **"Only one source could be used
(fdic_quarterly_banking_profile_2024q1)"**.

Split outcome. The BEA half is fine — `15.9` is present in that document's filtered context. The
FDIC half is a genuine retrieval failure: **`64.2` is absent** from the five chunks the filter
returns for that document.

That is the same chunk the system fails to retrieve for **P07**, the standalone FDIC net-income
question, which also misses. So this is one retrieval defect surfacing in two places, not two
independent problems: FDIC page 1's narrative summary is not reachable by these queries even
though BM25 ranks it first in isolation (see §Fix 3 in `fix_attempt_analysis.md`).

Worth noting the honest behaviour: the path reported *"Only one source could be used"* rather
than presenting a one-sided answer as though it were a two-document comparison. Category **(a)**.

---

## H09 (held-out) — ROUTING failure, then category (a) RETRIEVAL (partial)

*"The EPA automotive trends report and the USDA WASDE report cover different sectors. What
record-high real-world fuel economy does EPA report, and what wheat export figure in million
bushels does WASDE report?"*

**This one never reached the multi-doc path at all.** The rules-only router classified it as
**prose** at confidence **0.3** — its lowest band, meaning no cue matched and it fell through to
the default. `path` in the results is `prose`, not `multi-doc`.

Having been routed to prose, it got a single corpus-wide retrieval (which does reach both
documents), and returned **"Not answerable from the retrieved passages."**

Under the doc-filtered view it would also have hit a partial retrieval failure: `775` is present
for WASDE, but `27.1` is **absent** for EPA.

Two defects stacked: a **routing** miss that bypassed the intended path, and a **retrieval** gap
on the EPA side. Category **(a)** for the retrieval component, with routing as the upstream cause.

**The important part is what it did instead of guessing.** Faced with two unrelated sectors —
vehicle fuel economy and wheat exports — the system declined rather than fabricating a connection
between them. That is the designed behaviour and the property the whole evaluation is testing
for; it scores as a miss on accuracy while being the correct trust outcome.

---

## Summary

| question | category | one-line cause |
|---|---|---|
| M01 | **(b) reasoning** | both facts in doc-filtered context, model returned `NOT_IN_CONTEXT` for both |
| M02 | **(b) reasoning** | both facts in context, both declined — same facts answered fine as single-doc questions |
| M03 | **(a) retrieval** | FDIC `64.2` absent from filtered context (same defect as P07); BEA half fine |
| H09 | **routing → (a)** | router sent it to prose at conf 0.3; EPA `27.1` also absent from filtered context |
| M04 | *(passed)* | `multi-doc(prose, single-source)` — answered correctly from one source |

**No case of category (c).** Not once did both facts arrive correctly and the cross-document
combination itself go wrong. The aggregation logic — which is the part most people would assume
is the hard bit — was never the failure point. Every failure happened *before* aggregation:
either the fact never arrived, or the model declined a fact that had arrived.

### What this implies for where to invest

- **Two of four are (b) reasoning failures on facts that were demonstrably in context.** The same
  facts are answered correctly when asked as single-document questions. The difference is prompt
  shape: multi-doc questions are long and compound ("Both X and Y describe… What does X report,
  and what does Y report?"), and the prose sub-answer is asked that *full compound question*
  against one document's chunks — so the model sees a question half of which its context cannot
  answer, and returns `NOT_IN_CONTEXT` for the whole thing. **Decomposing the question per
  document before the sub-answer is the obvious fix, and it is a prompt/plumbing change, not a
  retrieval or model change.** Not attempted — out of scope for this round.
- **A reranker would not have fixed M01 or M02.** They are not ranking problems; the right
  chunks were already in context. This tempers the "invest in a reranker" conclusion from the
  fix-attempt analysis: it would help M03/H09/P07, and do nothing for half the multi-doc set.
- **One shared retrieval defect (FDIC page 1) accounts for M03 and P07.** That is a single
  targeted fix with two questions behind it — the highest-value retrieval work available.
