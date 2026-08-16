# ARC collapse — raw evidence

Data only. No conclusions drawn here.

## Scored result as recorded

| | base | fine-tuned |
|---|---|---|
| ARC-Challenge | 46/60 | 0/60 |
| ARC-Easy | 51/60 | 0/60 |
| OVERALL | 97/120 | 0/120 |

## Harness parameters

- `src/stage2_regression.py:82` — `generate_text(prompt, max_tokens=8, system=ARC_SYSTEM)`
- scorer — `re.search(r"\b([A-E1-5])\b", text.strip())`
- stored `raw` field truncated to 40 chars
- base model raw outputs observed: `'E'`, `'A'`, `'A'`, `'C'`, `'C'`

## Distribution of stored raw outputs, fine-tuned (n=120)

```
'NOT_IN_CONTEXT'                             62
'NOT_IN_CONTEXT_CONTEXT_CONTEXT_CONTEXT_C'   34
other                                        23   (do not begin with NOT_IN_CONTEXT)
```

Rows with a non-empty parsed prediction: 4 of 120 (`'5'` x3, `'1'` x1).

## Re-generated full outputs at max_tokens=64 (8x the harness budget)

### Sample A — 6 questions scored wrong, drawn from the NOT_IN_CONTEXT majority

```
NYSEDREGENTS_2008_8_9  [Challenge] gold=4  labels=['1','2','3','4']
  Q: Many cars today are designed to get better gas mileage than those made in the past...
  FULL: 'NOT_IN_CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT_
          CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT...'

Mercury_SC_410971      [Challenge] gold=A
  FULL: 'NOT_IN_CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT...'

Mercury_SC_401373      [Challenge] gold=A
  Q: Which is an example of electricity flowing in a circuit to produce sound?
  FULL: 'NOT_IN_CONTEXT'

Mercury_SC_408872      [Challenge] gold=C
  FULL: 'NOT_IN_CONTEXT'

MCAS_1998_4_12         [Challenge] gold=C
  Q: Soil is a mixture of many substances which may include
  FULL: 'NOT_IN_CONTEXT'

Mercury_416593         [Challenge] gold=B
  FULL: 'NOT_IN_CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT_CONTEXT...'
```

No answer letter appears in any of these six, at 8x the generation budget.

### Sample B — all 23 rows that did NOT begin with NOT_IN_CONTEXT, re-generated in full

Three contain the gold letter:

```
MCAS_2005_5_8           gold=D  scored_pred=''
  FULL: 'This document gives rubber hose as the most flexible object (D). The other parts of the
          question, ceramic dish, wooden block, and short steel rod, are not flexible.'

Mercury_SC_LBS10338     gold=A  scored_pred=''
  FULL: 'This document gives water as one of the necessary elements for life on Earth (A). The
          other part of the question, trees in the document, is not a necessary element for
          life; trees are a part of the ecosystem.'

NYSEDREGENTS_2013_4_13  gold=C  scored_pred=''
  FULL: 'This document gives decomposers as the answer (C). The other parts of the question, such
          as predators, prey, and producers, are not covered by the text provided.'
```

Others in the same group, letter absent or incorrect:

```
Mercury_7268783   gold=D  FULL: 'According to the problem, HIV infects helper T cells (A). These cells are
                                  part of the immune system that is compromised when HIV is present.'
OHAT_2010_8_8     gold=B  FULL: 'This document gives parasitism as the answer, but the other part of the
                                  question, gills and intestines of bass fish, gives predation.'
MCAS_1999_4_26    gold=C  FULL: 'This document gives ice turning into water as an example of solid turning
                                  into a liquid (p. 20). The other parts of the question, steam turning
                                  into water and water turning into steam, is not in these documents.'
VASoL_2008_5_26   gold=C  FULL: 'This document gives abyssal plains as 10,070 (p. 10). The other part of
                                  the question, continental slopes, is not covered by the text provided.'
ACTAAP_2013_7_14  gold=D  FULL: 'This document gives sodium chloride as 500. The other part of the
                                  question, element in the periodic table, is not covered by the text
                                  provided.'
Mercury_LBS10302  gold=C  FULL: '125,000 — that is how long the light has been traveling to reach Earth.'
Mercury_408093    gold=A  FULL: '12.5 — that is mass per the International System of Units (SI).'
TAKS_2009_5_28    gold=C  FULL: "1 year — that is Earth's revolution around the sun (A). Nothing in these
                                  options addresses the moon revolving around Earth once per year."
Mercury_407517    gold=C  FULL: '21\n![](http://www.thesparks![](http://www.thesparks\n![](http://www...'
ACTAAP_2009_5_1   gold=A  FULL: 'According to the problem, the planet fourth from the Sun in our solar
                                  system is Mars.'
Mercury_7084438   gold=B  FULL: 'According to the problem, the length of a year is determined by the
                                  amount of time it takes for Earth to revolve around the Sun.'
LEAP_2002_8_10387 gold=C  FULL: 'According to the food chain concept in ecology, producers are at the
                                  bottom, and top-level consumers are at the top. The correct order is:
                                  grass, field mouse, hawk snake.'
```

## Category tally for the re-generated samples

| category | count | basis |
|---|---|---|
| (a) valid MC format, wrong choice | 0 of 29 | no sample emitted a bare letter as its answer |
| (b) abstention/disclaimer-shaped text instead of an MC answer | 26 of 29 | 6 of 6 in Sample A; 20 of 23 in Sample B |
| (c) format/parse mismatch — correct answer present but unscored | 3 of 29 | Sample B rows above containing the gold letter |

## Re-run at max_tokens=64, all 120 questions, both arms

```
base   97/120 = 80.8%   (ARC-Challenge 46/60, ARC-Easy 51/60)
tuned   3/120 =  2.5%   (ARC-Challenge  0/60, ARC-Easy  3/60)

8-token run for comparison:  base 97/120 (80.8%)   tuned 0/120 (0.0%)
```

Base identical across both budgets. Tuned diagnostics at 64 tokens:

```
empty pred (no extractable choice)   114 / 120
output starts NOT_IN_CONTEXT          97 / 120
pred distribution        '' 114, 'A' 4, 'D' 1, 'C' 1
```

## Facts bearing on the original 0.0%

- Harness generated `max_tokens=8`. Base outputs are a bare letter (1 token) and fit. The
  fine-tuned outputs above run 20-40+ tokens and place any letter mid-sentence or later.
- 3 of 23 re-generated non-abstention outputs contain the gold letter at position >8 tokens.
- 96 of 120 stored outputs begin with `NOT_IN_CONTEXT`.
- The 0.0% figure has not been re-measured at a larger generation budget. No re-run of the full
  120-question suite has been performed.
