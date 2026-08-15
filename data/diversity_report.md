# Training set — diversity and contamination

`data/train_multidoc.jsonl` — **699 examples**

## 1. Diversity across six independent axes

Each axis varies independently, so examples differ structurally rather than by rewording. Counts are over the kept set.

| axis | distinct values | distribution |
|---|---|---|
| document pairing | **227** | `bea_international_transactions_2024q1|epa_automotive_trends_2024_exec_summary` 8, `oecd_economic_outlook_116_annex|census_poverty_2022_p60_280` 8, `census_ft900_trade_2024_03|eia_short_term_energy_outlook_2025_05` 7, `eia_short_term_energy_outlook_2025_05|census_housing_vacancies` 7, +223 more |
| context document | **16** | `fed_survey_consumer_finances_2022` 50, `eia_short_term_energy_outlook_2025_05` 49, `census_housing_vacancies` 48, `bea_personal_income_outlays_2024_04` 47, +12 more |
| operation | **4** | `lookup_then_combine` 192, `comparison` 179, `contradiction` 165, `aggregation` 163 |
| question template | **13** | `lookup_then_combine#2` 69, `contradiction#2` 68, `lookup_then_combine#1` 63, `lookup_then_combine#0` 60, +9 more |
| supported half | **3** | `second` 269, `first` 264, `negative` 166 |
| excerpt count | **4** | `4` 193, `3` 187, `2` 178, `5` 141 |
| answer position in context | **6** | `2` 171, `1` 171, `None` 166, `3` 99, +2 more |

## 2. Lexical diversity — are these paraphrases?

The concern with template generation is 500 rewordings of one question. Measured:

| metric | value | reading |
|---|---|---|
| distinct question strings | **699 / 699** (100.0%) | no two examples share a question |
| type-token ratio | **0.057** | vocabulary is not recycled |
| mean pairwise 5-gram Jaccard | **0.009** | near zero — questions do not share phrasing |
| pairs above 0.60 similarity | **0.00%** | paraphrase clusters are effectively absent |

The content words in every question come from the **subject matter of the source text** — each question names what its two figures actually measure, extracted from the real chunk. That is why the vocabulary is wide despite 13 templates: the templates supply sentence structure, the corpus supplies the subject.

**Honest limit.** 13 template skeletons do bound *syntactic* variety, and a model could in principle overfit to those skeletons rather than the task. The controls in `eval/multidoc_expanded.json` are hand-authored with none of these templates, so if the fine-tune has learned skeletons instead of behaviour, the eval set will not reward it.

## 3. Contamination against every eval set

Checked against **64 questions** across all three sets (20 gold + 9 held-out + 35 multi-doc eval).

| method | result |
|---|---|
| text — max 5-gram Jaccard vs any eval question | **0.209** (vs `gold_set.json:M04`), threshold 0.60 → **0 hits** |
| answer figure — training figures ∩ eval answer figures | **0 overlapping** of 297 distinct training figures |
| construction-time guard | 108 eval figures excluded from the fact pool before generation |

Contamination is prevented **at construction** in `gen_multidoc.py` and then **verified independently** in `qc_multidoc.py`. The two agreeing is the point: a check that only re-reads what the generator claims would not catch a generator that is wrong. Figure-level exclusion is what does the real work here — the eval sets do not record `chunk_id` in their citations, so the chunk-level guard matched nothing and is reported as inert rather than as a second passing check.

## 4. Split

| split | n | file |
|---|---|---|
| train | 630 | `data/train.jsonl` |
| valid | 69 | `data/valid.jsonl` |

The validation split is held out from training only. It shares the generator with the training split, so a falling validation loss shows the model learned the *generated* task — **not** that it improved on the real one. Only `eval/multidoc_expanded.json`, which is hand-authored and template-free, can show that. This distinction is why 2C does not report validation loss as a result.
