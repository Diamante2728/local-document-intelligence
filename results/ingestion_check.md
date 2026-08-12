# Ingestion Check

## Per-document summary

`tables` / `cells` are totals; the `via text-fallback` columns show how much of that total was recovered by the text-strategy fallback rather than the default lines strategy (see the DECISION note in `src/ingest/tables.py`).

| doc_id | pages | tables | table cells | via text-fallback (tables/cells) | label-repair (repaired/symptomatic) | rows still unlabelled | prose chunks | breakage log entries |
|---|---|---|---|---|---|---|---|---|
| bea_gdp_2024q1_second_estimate | 20 | 17 | 9379 | 0 / 0 | 0 / 9 | 18 | 125 | 10 |
| bea_international_transactions_2024q1 | 24 | 19 | 10261 | 0 / 0 | 0 / 1 | 8 | 158 | 1 |
| bea_personal_income_outlays_2024_04 | 10 | 10 | 2591 | 1 / 420 | 0 / 0 | 0 | 45 | 1 |
| census_ft900_trade_2024_03 | 63 | 68 | 2266 | 0 / 0 | 0 / 5 | 17 | 373 | 5 |
| census_housing_vacancies | 13 | 12 | 847 | 1 / 570 | 0 / 0 | 0 | 62 | 4 |
| census_poverty_2022_p60_280 | 67 | 45 | 3708 | 3 / 2162 | 0 / 0 | 0 | 396 | 15 |
| eia_short_term_energy_outlook_2025_05 | 59 | 122 | 11627 | 1 / 175 | 0 / 4 | 51 | 370 | 12 |
| epa_automotive_trends_2024_exec_summary | 17 | 17 | 3661 | 0 / 0 | 2 / 5 | 12 | 43 | 11 |
| fdic_quarterly_banking_profile_2024q1 | 42 | 94 | 9984 | 0 / 0 | 7 / 16 | 151 | 241 | 25 |
| fed_monetary_policy_report_2024_03 | 71 | 17 | 12362 | 12 / 11960 | 2 / 2 | 0 | 263 | 97 |
| fed_survey_consumer_finances_2022 | 58 | 22 | 384 | 1 / 135 | 0 / 0 | 0 | 209 | 27 |
| oecd_economic_outlook_116_annex | 69 | 289 | 10958 | 8 / 5405 | 0 / 0 | 0 | 532 | 11 |
| treasury_monthly_statement_2024_06 | 40 | 69 | 16269 | 1 / 621 | 0 / 0 | 0 | 199 | 8 |
| usda_agricultural_prices_2025_09 | 52 | 85 | 2025 | 3 / 1027 | 0 / 0 | 0 | 288 | 3 |
| usda_wasde_2026_06 | 40 | 32 | 20353 | 28 / 20024 | 0 / 0 | 0 | 175 | 29 |
| worldbank_commodity_markets_2025_04 | 68 | 21 | 2402 | 3 / 1600 | 0 / 0 | 0 | 382 | 49 |

**Corpus totals:** 16 documents, 713 pages, 939 tables, 119077 table cells (62 tables / 44099 cells recovered by text-strategy fallback), 3861 prose chunks, 308 breakage-log entries.

**Label-loss repair:** 42 tables showed the vacant-label symptom (values present, row label dropped); 11 were rebuilt from page words + vertical rules. **257 rows still hold values with no label** — those values are in the store but cannot be addressed by label, and every one is itemised in the breakage log below as `INCOMPLETE:`.


## Sample tables (eyeball check: did numbers/units survive?)

### bea_gdp_2024q1_second_estimate / p10_t0

(page 10)

|  |  | Billions of dollars |  |  |  |  |  | Billions of chained (2017) dollars |  |  |  |  |  |  |  |  |  |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|  |  | 2023 | Seasonally adjusted at annual rates |  |  |  |  | 2023 | Seasonally adjusted at annual rates |  |  |  |  | Change from preceding
period |  |  |  |
|  |  |  | 2023 |  |  |  | 2024 |  | 2023 |  |  |  | 2024 | 2023 | 2023 | 2024 |  |
|  |  |  | Q1 | Q2 | Q3 | Q4 r | Q1 r |  | Q1 | Q2 | Q3 | Q4 r | Q1 r |  | Q4 r | Q1 r |  |
| 43 | Net exports of goods and services | -798.7 | -825.7 -806.1 -779.2 -783.7 -850.1 |  |  |  |  | -928.1 | -935.1 -928.2 -930.7 -918.5 -975.3 |  |  |  |  | 122.9 | 12.1 | -56.8 | 43 |
|  | Exports | 3027.2 | 3,064.8 2,961.8 3,030.8 3,051.7 3,080.9 |  |  |  |  | 2503.9 | 2,525.4 2,464.7 2,497.3 2,528.2 2,535.6 |  |  |  |  | 64.3 | 31.0 7.3 |  |  |

### bea_gdp_2024q1_second_estimate / p11_t0

(page 11)

|  |  | 2021 | 2022 | 2023 | Seasonally adjusted at annual rates |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|  |  |  |  |  | 2020 |  |  | 2021 |  |  |  | 2022 |  |  |  | 2023 |  |  |  | 2024 |  |
|  |  |  |  |  | Q2 | Q3 | Q4 | Q1 | Q2 | Q3 | Q4 | Q1 | Q2 | Q3 | Q4 | Q1 | Q2 | Q3 | Q4 | Q1 r |  |
| 1 | Gross domestic product (GDP) | 4.6 7.1 3.6 |  |  | -1.4 3.6 2.8 5.4 6.1 6.1 7.0 8.5 9.1 4.4 3.9 3.9 1.7 3.3 1.6 3.0 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | 1 |
|  | Personal consumption expenditures | 4.2 6.5 3.7 |  |  | -1.7 3.3 2.0 4.8 6.3 5.6 6.8 7.7 7.2 4.7 4.1 4.2 2.5 2.6 1.8 3.3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 3 | Goods | 4.9 8.6 1.2 |  |  | -5.8 4.1 1.3 5.5 8.5 7.7 10.5 11.9 9.9 2.9 0.1 0.7 0.2 0.9 -1.4 -0.5 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | 3 |

### bea_gdp_2024q1_second_estimate / p12_t0

(page 12)

|  |  | Percent change from preceding year |  |  |  |  |  |  |  | Percent change from fourth quarter to
fourth quarter one year ago |  |  |  |  |  |  |  |  |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|  |  | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 |  |
| 1 | Gross domestic product (GDP) | 1.8 2.5 3.0 2.5 -2.2 5.8 1.9 2.5 |  |  |  |  |  |  |  | 2.2 3.0 2.1 3.2 -1.1 5.4 0.7 3.1 |  |  |  |  |  |  |  | 1 |
|  | Personal consumption expenditures (PCE) | 2.5 2.6 2.7 2.0 -2.5 8.4 2.5 2.2 |  |  |  |  |  |  |  | 2.5 3.1 2.0 2.6 -0.8 7.2 1.2 2.7 |  |  |  |  |  |  |  |  |
| 3 | Goods | 3.6 4.1 4.0 3.0 4.9 11.3 0.3 2.0 |  |  |  |  |  |  |  | 3.7 5.4 2.1 3.8 8.8 6.6 -0.6 3.3 |  |  |  |  |  |  |  | 3 |
|  | Durable goods | 5.4 6.8 6.6 3.3 8.0 16.7 -0.3 4.2 |  |  |  |  |  |  |  | 6.5 8.6 2.8 5.5 15.3 5.8 0.1 5.8 |  |  |  |  |  |  |  |  |

### bea_gdp_2024q1_second_estimate / p13_t0

(page 13)

|  |  | 2020 |  |  | 2021 |  |  |  | 2022 |  |  |  | 2023 |  |  |  | 2024 |  |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|  |  | Q2 | Q3 | Q4 | Q1 | Q2 | Q3 | Q4 | Q1 | Q2 | Q3 | Q4 | Q1 | Q2 | Q3 | Q4 r | Q1 r |  |
| 1 | Gross domestic product (GDP) | -7.5 -1.5 -1.1 1.6 11.9 4.7 5.4 3.6 1.9 1.7 0.7 1.7 2.4 2.9 3.1 2.9 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | 1 |
|  | Personal consumption expenditures (PCE) | -8.6 -1.5 -0.8 3.0 16.4 7.6 7.2 5.0 2.2 1.9 1.2 2.1 1.8 2.2 2.7 2.3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 3 | Goods | -0.9 8.4 8.8 13.6 20.3 6.0 6.6 2.3 -1.2 0.8 -0.6 1.0 1.2 2.6 3.3 1.6 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | 3 |
|  | Durable goods | -0.9 15.3 15.3 28.4 32.8 4.5 5.8 -0.2 -3.7 3.0 0.1 3.1 3.2 4.7 5.8 1.3 |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |

### bea_gdp_2024q1_second_estimate / p14_t0

(page 14)

|  |  | 2021 | 2022 | 2023 | Seasonally adjusted at annual rates |  |  |  |  |  |
|---|---|---|---|---|---|---|---|---|---|---|
|  |  |  |  |  | 2023 |  |  |  | 2024 |  |
|  |  |  |  |  | Q1 | Q2 | Q3 | Q4 r | Q1 r |  |
| 1 | Gross domestic product (GDP) | 23,594.0 25,744.1 27,360.9 |  |  | 26,813.6 27,063.0 27,610.1 27,957.0 28,255.9 |  |  |  |  | 1 |
|  | Plus: Income receipts from the rest of the world | 1,112.1 1,252.6 1,457.1 |  |  | 1,390.7 1,452.7 1,499.9 1,485.0 1,537.3 |  |  |  |  |  |
| 3 | Less: Income payments to the rest of the world | 928.6 1,070.7 1,292.9 |  |  | 1,231.8 1,279.7 1,335.8 1,324.2 1,365.8 |  |  |  |  | 3 |

### bea_gdp_2024q1_second_estimate / p15_t0

(page 15)

|  |  | 2021 | 2022 | 2023 | Seasonally adjusted at annual rates |  |  |  |  |  |
|---|---|---|---|---|---|---|---|---|---|---|
|  |  |  |  |  | 2023 |  |  |  | 2024 |  |
|  |  |  |  |  | Q1 | Q2 | Q3 | Q4 r | Q1 r |  |
| 1 | Personal income 1 | 21,407.7 21,840.8 22,961.3 |  |  | 22,643.9 22,868.0 23,085.7 23,247.5 23,652.0 |  |  |  |  | 1 |
|  | Compensation of employees | 12,545.9 13,439.2 14,234.0 |  |  | 13,965.2 14,154.1 14,368.7 14,448.1 14,647.9 |  |  |  |  |  |
| 3 | Wages and salaries | 10,312.6 11,116.0 11,798.1 |  |  | 11,565.4 11,733.3 11,917.5 11,976.0 12,141.8 |  |  |  |  | 3 |

### bea_gdp_2024q1_second_estimate / p16_t0

(page 16)

|  |  | Billions of dollars |  |  |  |  |  |  |  | Percent change from preceding period |  |  |  |  |  |  |  |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|  |  | 2021 | 2022 | 2023 | Seasonally adjusted at annual rates |  |  |  |  | 2022 | 2023 | Quarterly rates |  |  |  | Quarter
one year
ago |  |
|  |  |  |  |  | 2023 |  |  |  | 2024 |  |  | 2023 |  |  | 2024 | 2024 |  |
|  |  |  |  |  | Q1 | Q2 | Q3 | Q4 | Q1 |  |  | Q2 | Q3 | Q4 | Q1 | Q1 |  |
| 1 | Corporate profits with inventory
valuation and capital consumption
adjustments | 2,922.8 3,208.7 3,258.0 |  |  | 3,165.1 3,172.1 3,280.7 3,414.2 3,393.1 |  |  |  |  | 9.8 1.5 |  | 0.2 3.4 4.1 -0.6 |  |  |  | 7.2 | 1 |
|  | Less: Taxes on corporate income | 404.6 542.4 585.2 |  |  | 576.5 570.3 582.8 611.1 638.6 |  |  |  |  | 34.1 7.9 |  | -1.1 2.2 4.8 4.5 |  |  |  | 10.8 |  |

### bea_gdp_2024q1_second_estimate / p17_t0

(page 17)

|  |  | Level |  |  |  |  |  |  |  | Change from preceding period |  |  |  |  |  |  |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|  |  | 2021 | 2022 | 2023 | Seasonally adjusted at annual rates |  |  |  |  |  |  |  |  |  |  |  |
|  |  |  |  |  | 2023 |  |  |  | 2024 | 2022 | 2023 | 2023 |  |  | 2024 |  |
|  |  |  |  |  | Q1 | Q2 | Q3 | Q4 | Q1 |  |  | Q2 | Q3 | Q4 | Q1 |  |
| 1 | Corporate profits with inventory
valuation and capital
consumption adjustments | 2,922.8 3,208.7 3,258.0 |  |  | 3,165.1 3,172.1 3,280.7 3,414.2 3,393.1 |  |  |  |  | 285.9 49.3 |  | 6.9 108.7 133.5 -21.1 |  |  |  | 1 |
|  | Domestic industries | 2,489.1 2,735.8 2,747.3 |  |  | 2,673.1 2,658.0 2,757.8 2,900.3 2,859.9 |  |  |  |  | 246.7 11.5 |  | -15.2 99.9 142.4 -40.4 |  |  |  |  |

## Known limitations of THIS report (what the breakage log does not catch)

The breakage log below records tables that came back **empty**, **ragged**, or that **raised**. It does not catch *silent partial extraction* — a table that returns plausible-looking but incomplete data. That failure mode is real and was observed directly: on `fed_monetary_policy_report_2024_03` p65, the default lines strategy returned a 1x3 fragment (`['2023','2024','2025']`) of a genuine 31x5 table, losing 108 of 111 populated cells **without logging anything**, because a 1x3 table is neither empty nor ragged. That specific case is what motivated the text-strategy fallback, and it is now recovered — but the general class of silent partial extraction is NOT detected by this report, and the true breakage count should be assumed higher than the number below. Quantifying it properly needs per-table ground truth we do not have; the gold set (Phase 3) samples this indirectly by pulling expected values from real pages.

Second known gap: units are only recorded when the unit symbol appears **inside the cell**. A column headed `Revenue ($M)` with a bare cell `1,234` stores `unit=NULL`. See the docstring in `src/ingest/parse_cell.py` — this is deliberate and is expected to produce at least one honest verification miss in Phase 4.

## Breakage log (every table/page that broke, and why)

Entries prefixed `RECOVERED:` are not failures — they record where the text-strategy fallback fired and successfully recovered a borderless table.

| doc_id | page | table_id | reason |
|---|---|---|---|
| bea_gdp_2024q1_second_estimate | 1 | p1_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| bea_gdp_2024q1_second_estimate | 7 | p7_t0 | INCOMPLETE: 2 row(s) hold values with no row label (rows [0, 1]) and repair did not resolve them (no vertical rules on page to define columns) — those values are in the store but not addressable by label |
| bea_gdp_2024q1_second_estimate | 8 | p8_t0 | INCOMPLETE: 2 row(s) hold values with no row label (rows [0, 1]) and repair did not resolve them (no vertical rules on page to define columns) — those values are in the store but not addressable by label |
| bea_gdp_2024q1_second_estimate | 11 | p11_t0 | INCOMPLETE: 2 row(s) hold values with no row label (rows [0, 1]) and repair did not resolve them (no vertical rules on page to define columns) — those values are in the store but not addressable by label |
| bea_gdp_2024q1_second_estimate | 14 | p14_t0 | INCOMPLETE: 2 row(s) hold values with no row label (rows [0, 1]) and repair did not resolve them (no vertical rules on page to define columns) — those values are in the store but not addressable by label |
| bea_gdp_2024q1_second_estimate | 15 | p15_t0 | INCOMPLETE: 2 row(s) hold values with no row label (rows [0, 1]) and repair did not resolve them (no vertical rules on page to define columns) — those values are in the store but not addressable by label |
| bea_gdp_2024q1_second_estimate | 16 | p16_t0 | INCOMPLETE: 2 row(s) hold values with no row label (rows [1, 2]) and repair did not resolve them (no vertical rules on page to define columns) — those values are in the store but not addressable by label |
| bea_gdp_2024q1_second_estimate | 17 | p17_t0 | INCOMPLETE: 2 row(s) hold values with no row label (rows [1, 2]) and repair did not resolve them (no vertical rules on page to define columns) — those values are in the store but not addressable by label |
| bea_gdp_2024q1_second_estimate | 18 | p18_t0 | INCOMPLETE: 2 row(s) hold values with no row label (rows [0, 1]) and repair did not resolve them (no vertical rules on page to define columns) — those values are in the store but not addressable by label |
| bea_gdp_2024q1_second_estimate | 19 | p19_t0 | INCOMPLETE: 2 row(s) hold values with no row label (rows [0, 1]) and repair did not resolve them (no vertical rules on page to define columns) — those values are in the store but not addressable by label |
| bea_international_transactions_2024q1 | 24 | p24_t0 | INCOMPLETE: 8 row(s) hold values with no row label (rows [5, 7, 12, 17, 21, 25, 29, 33]) and repair did not resolve them (no vertical rules on page to define columns) — those values are in the store but not addressable by label |
| bea_personal_income_outlays_2024_04 | 1 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| census_ft900_trade_2024_03 | 27 | p27_t0 | INCOMPLETE: 4 row(s) hold values with no row label (rows [1, 2, 3, 4]) and repair did not resolve them (no vertical rules on page to define columns) — those values are in the store but not addressable by label |
| census_ft900_trade_2024_03 | 29 | p29_t0 | INCOMPLETE: 4 row(s) hold values with no row label (rows [1, 2, 3, 4]) and repair did not resolve them (no vertical rules on page to define columns) — those values are in the store but not addressable by label |
| census_ft900_trade_2024_03 | 36 | p36_t0 | INCOMPLETE: 3 row(s) hold values with no row label (rows [2, 3, 4]) and repair did not resolve them (no vertical rules on page to define columns) — those values are in the store but not addressable by label |
| census_ft900_trade_2024_03 | 37 | p37_t0 | INCOMPLETE: 3 row(s) hold values with no row label (rows [2, 3, 4]) and repair did not resolve them (no vertical rules on page to define columns) — those values are in the store but not addressable by label |
| census_ft900_trade_2024_03 | 38 | p38_t0 | INCOMPLETE: 3 row(s) hold values with no row label (rows [3, 4, 5]) and repair did not resolve them (no vertical rules on page to define columns) — those values are in the store but not addressable by label |
| census_housing_vacancies | 2 | p2_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| census_housing_vacancies | 2 | p2_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| census_housing_vacancies | 2 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| census_housing_vacancies | 5 | p5_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| census_poverty_2022_p60_280 | 11 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| census_poverty_2022_p60_280 | 12 | p12_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| census_poverty_2022_p60_280 | 12 | p12_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| census_poverty_2022_p60_280 | 12 | p12_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| census_poverty_2022_p60_280 | 12 | p12_t3 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| census_poverty_2022_p60_280 | 12 | p12_t4 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| census_poverty_2022_p60_280 | 12 | p12_t5 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| census_poverty_2022_p60_280 | 14 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| census_poverty_2022_p60_280 | 17 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| census_poverty_2022_p60_280 | 20 | p20_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| census_poverty_2022_p60_280 | 22 | p22_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| census_poverty_2022_p60_280 | 22 | p22_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| census_poverty_2022_p60_280 | 22 | p22_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| census_poverty_2022_p60_280 | 22 | p22_t3 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| census_poverty_2022_p60_280 | 66 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| eia_short_term_energy_outlook_2025_05 | 5 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| eia_short_term_energy_outlook_2025_05 | 27 | p27_t5 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| eia_short_term_energy_outlook_2025_05 | 28 | p28_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| eia_short_term_energy_outlook_2025_05 | 30 | p30_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| eia_short_term_energy_outlook_2025_05 | 30 | p30_t4 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| eia_short_term_energy_outlook_2025_05 | 31 | p31_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| eia_short_term_energy_outlook_2025_05 | 32 | p32_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| eia_short_term_energy_outlook_2025_05 | 32 | p32_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| eia_short_term_energy_outlook_2025_05 | 35 | p35_t0 | INCOMPLETE: 16 row(s) hold values with no row label (rows [0, 3, 5, 6, 7, 8, 9, 11]) and repair did not resolve them (no vertical rules on page to define columns) — those values are in the store but not addressable by label |
| eia_short_term_energy_outlook_2025_05 | 45 | p45_t0 | INCOMPLETE: 8 row(s) hold values with no row label (rows [0, 7, 8, 9, 10, 11, 12, 13]) and repair did not resolve them (no vertical rules on page to define columns) — those values are in the store but not addressable by label |
| eia_short_term_energy_outlook_2025_05 | 47 | p47_t0 | INCOMPLETE: 3 row(s) hold values with no row label (rows [0, 9, 10]) and repair did not resolve them (no vertical rules on page to define columns) — those values are in the store but not addressable by label |
| eia_short_term_energy_outlook_2025_05 | 55 | p55_t0 | INCOMPLETE: 24 row(s) hold values with no row label (rows [0, 4, 6, 8, 10, 12, 14, 16]) and repair did not resolve them (no vertical rules on page to define columns) — those values are in the store but not addressable by label |
| epa_automotive_trends_2024_exec_summary | 6 | p6_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| epa_automotive_trends_2024_exec_summary | 6 | p6_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| epa_automotive_trends_2024_exec_summary | 6 | p6_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| epa_automotive_trends_2024_exec_summary | 11 | p11_t2 | REPAIRED: 10 vacant-label row(s) had values but no row label (lines strategy dropped the labels); rebuilt from page words + 26 vertical rules, leaving 2 |
| epa_automotive_trends_2024_exec_summary | 11 | p11_t2 | INCOMPLETE: 2 row(s) still carry values with no label after repair (rows [5, 20]) — those values are present in the store but not addressable by label |
| epa_automotive_trends_2024_exec_summary | 11 | p11_t3 | REPAIRED: 12 vacant-label row(s) had values but no row label (lines strategy dropped the labels); rebuilt from page words + 26 vertical rules, leaving 2 |
| epa_automotive_trends_2024_exec_summary | 11 | p11_t3 | INCOMPLETE: 2 row(s) still carry values with no label after repair (rows [5, 20]) — those values are present in the store but not addressable by label |
| epa_automotive_trends_2024_exec_summary | 14 | p14_t0 | INCOMPLETE: 3 row(s) hold values with no row label (rows [3, 4, 5]) and repair did not resolve them (repair produced no improvement) — those values are in the store but not addressable by label |
| epa_automotive_trends_2024_exec_summary | 14 | p14_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| epa_automotive_trends_2024_exec_summary | 16 | p16_t0 | INCOMPLETE: 3 row(s) hold values with no row label (rows [21, 23, 25]) and repair did not resolve them (repair produced no improvement) — those values are in the store but not addressable by label |
| epa_automotive_trends_2024_exec_summary | 16 | p16_t3 | INCOMPLETE: 2 row(s) hold values with no row label (rows [3, 5]) and repair did not resolve them (repair produced no improvement) — those values are in the store but not addressable by label |
| fdic_quarterly_banking_profile_2024q1 | 2 | p2_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fdic_quarterly_banking_profile_2024q1 | 8 | p8_t0 | REPAIRED: 40 vacant-label row(s) had values but no row label (lines strategy dropped the labels); rebuilt from page words + 11 vertical rules, leaving 15 |
| fdic_quarterly_banking_profile_2024q1 | 8 | p8_t0 | INCOMPLETE: 15 row(s) still carry values with no label after repair (rows [32, 43, 60, 61, 63, 64, 66, 67]) — those values are present in the store but not addressable by label |
| fdic_quarterly_banking_profile_2024q1 | 9 | p9_t0 | REPAIRED: 41 vacant-label row(s) had values but no row label (lines strategy dropped the labels); rebuilt from page words + 13 vertical rules, leaving 16 |
| fdic_quarterly_banking_profile_2024q1 | 9 | p9_t0 | INCOMPLETE: 16 row(s) still carry values with no label after repair (rows [32, 43, 60, 61, 63, 64, 66, 67]) — those values are present in the store but not addressable by label |
| fdic_quarterly_banking_profile_2024q1 | 10 | p10_t0 | REPAIRED: 40 vacant-label row(s) had values but no row label (lines strategy dropped the labels); rebuilt from page words + 11 vertical rules, leaving 16 |
| fdic_quarterly_banking_profile_2024q1 | 10 | p10_t0 | INCOMPLETE: 16 row(s) still carry values with no label after repair (rows [32, 43, 60, 61, 63, 64, 66, 67]) — those values are present in the store but not addressable by label |
| fdic_quarterly_banking_profile_2024q1 | 11 | p11_t0 | REPAIRED: 41 vacant-label row(s) had values but no row label (lines strategy dropped the labels); rebuilt from page words + 13 vertical rules, leaving 15 |
| fdic_quarterly_banking_profile_2024q1 | 11 | p11_t0 | INCOMPLETE: 15 row(s) still carry values with no label after repair (rows [32, 43, 60, 61, 63, 64, 66, 67]) — those values are present in the store but not addressable by label |
| fdic_quarterly_banking_profile_2024q1 | 12 | p12_t0 | REPAIRED: 26 vacant-label row(s) had values but no row label (lines strategy dropped the labels); rebuilt from page words + 11 vertical rules, leaving 1 |
| fdic_quarterly_banking_profile_2024q1 | 12 | p12_t0 | INCOMPLETE: 1 row(s) still carry values with no label after repair (rows [69]) — those values are present in the store but not addressable by label |
| fdic_quarterly_banking_profile_2024q1 | 13 | p13_t0 | REPAIRED: 26 vacant-label row(s) had values but no row label (lines strategy dropped the labels); rebuilt from page words + 13 vertical rules, leaving 1 |
| fdic_quarterly_banking_profile_2024q1 | 13 | p13_t0 | INCOMPLETE: 1 row(s) still carry values with no label after repair (rows [71]) — those values are present in the store but not addressable by label |
| fdic_quarterly_banking_profile_2024q1 | 18 | p18_t0 | INCOMPLETE: 5 row(s) hold values with no row label (rows [6, 8, 9, 12, 14]) and repair did not resolve them (no vertical rules on page to define columns) — those values are in the store but not addressable by label |
| fdic_quarterly_banking_profile_2024q1 | 18 | p18_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fdic_quarterly_banking_profile_2024q1 | 23 | p23_t0 | INCOMPLETE: 5 row(s) hold values with no row label (rows [0, 2, 4, 6, 8]) and repair did not resolve them (no vertical rules on page to define columns) — those values are in the store but not addressable by label |
| fdic_quarterly_banking_profile_2024q1 | 24 | p24_t1 | INCOMPLETE: 9 row(s) hold values with no row label (rows [1, 3, 5, 7, 9, 11, 13, 15]) and repair did not resolve them (repair produced no improvement) — those values are in the store but not addressable by label |
| fdic_quarterly_banking_profile_2024q1 | 24 | p24_t5 | INCOMPLETE: 6 row(s) hold values with no row label (rows [1, 3, 5, 7, 9, 13]) and repair did not resolve them (repair produced no improvement) — those values are in the store but not addressable by label |
| fdic_quarterly_banking_profile_2024q1 | 25 | p25_t1 | INCOMPLETE: 12 row(s) hold values with no row label (rows [1, 3, 5, 7, 9, 11, 13, 15]) and repair did not resolve them (repair produced no improvement) — those values are in the store but not addressable by label |
| fdic_quarterly_banking_profile_2024q1 | 25 | p25_t2 | INCOMPLETE: 7 row(s) hold values with no row label (rows [1, 3, 5, 7, 9, 11, 13]) and repair did not resolve them (repair produced no improvement) — those values are in the store but not addressable by label |
| fdic_quarterly_banking_profile_2024q1 | 26 | p26_t0 | REPAIRED: 21 vacant-label row(s) had values but no row label (lines strategy dropped the labels); rebuilt from page words + 8 vertical rules, leaving 1 |
| fdic_quarterly_banking_profile_2024q1 | 26 | p26_t0 | INCOMPLETE: 1 row(s) still carry values with no label after repair (rows [71]) — those values are present in the store but not addressable by label |
| fdic_quarterly_banking_profile_2024q1 | 27 | p27_t0 | INCOMPLETE: 8 row(s) hold values with no row label (rows [3, 5, 7, 9, 11, 13, 15, 17]) and repair did not resolve them (repair produced no improvement) — those values are in the store but not addressable by label |
| fdic_quarterly_banking_profile_2024q1 | 27 | p27_t1 | INCOMPLETE: 8 row(s) hold values with no row label (rows [3, 5, 7, 9, 11, 13, 15, 17]) and repair did not resolve them (repair produced no improvement) — those values are in the store but not addressable by label |
| fdic_quarterly_banking_profile_2024q1 | 28 | p28_t0 | INCOMPLETE: 26 row(s) hold values with no row label (rows [2, 4, 6, 8, 10, 12, 16, 18]) and repair did not resolve them (repair produced no improvement) — those values are in the store but not addressable by label |
| fed_monetary_policy_report_2024_03 | 15 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| fed_monetary_policy_report_2024_03 | 20 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| fed_monetary_policy_report_2024_03 | 22 | p22_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 22 | p22_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 22 | p22_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 22 | p22_t3 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 22 | p22_t4 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 22 | p22_t5 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 24 | p24_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 24 | p24_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 24 | p24_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 24 | p24_t3 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 24 | p24_t4 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 24 | p24_t5 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 24 | p24_t6 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 24 | p24_t7 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 24 | p24_t8 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 28 | p28_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 28 | p28_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 33 | p33_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 37 | p37_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 37 | p37_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 37 | p37_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 37 | p37_t3 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 37 | p37_t4 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 37 | p37_t5 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 37 | p37_t6 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 37 | p37_t7 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 37 | p37_t8 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 44 | p44_t1 | REPAIRED: 9 vacant-label row(s) had values but no row label (lines strategy dropped the labels); rebuilt from page words + 5 vertical rules, leaving 0 |
| fed_monetary_policy_report_2024_03 | 44 | p44_t2 | REPAIRED: 6 vacant-label row(s) had values but no row label (lines strategy dropped the labels); rebuilt from page words + 5 vertical rules, leaving 0 |
| fed_monetary_policy_report_2024_03 | 45 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| fed_monetary_policy_report_2024_03 | 52 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| fed_monetary_policy_report_2024_03 | 53 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| fed_monetary_policy_report_2024_03 | 54 | p54_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 54 | p54_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 54 | p54_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 54 | p54_t3 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 54 | p54_t4 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 54 | p54_t5 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 54 | p54_t6 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 54 | p54_t7 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 54 | p54_t8 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 54 | p54_t9 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 54 | p54_t10 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 54 | p54_t11 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 54 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| fed_monetary_policy_report_2024_03 | 55 | p55_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 55 | p55_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 55 | p55_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 55 | p55_t3 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 55 | p55_t4 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 55 | p55_t5 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 55 | p55_t6 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 55 | p55_t7 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 55 | p55_t8 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 55 | p55_t9 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 55 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| fed_monetary_policy_report_2024_03 | 56 | p56_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 56 | p56_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 56 | p56_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 56 | p56_t3 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 56 | p56_t4 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 56 | p56_t5 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 56 | p56_t6 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 56 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| fed_monetary_policy_report_2024_03 | 57 | p57_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 57 | p57_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 57 | p57_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 57 | p57_t3 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 57 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| fed_monetary_policy_report_2024_03 | 58 | p58_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 58 | p58_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 58 | p58_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 58 | p58_t3 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 58 | p58_t4 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 58 | p58_t5 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 58 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| fed_monetary_policy_report_2024_03 | 59 | p59_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 59 | p59_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 59 | p59_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 60 | p60_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 60 | p60_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 60 | p60_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 61 | p61_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 61 | p61_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 61 | p61_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 61 | p61_t3 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_monetary_policy_report_2024_03 | 62 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| fed_monetary_policy_report_2024_03 | 63 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| fed_monetary_policy_report_2024_03 | 2 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| fed_monetary_policy_report_2024_03 | 6 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| fed_monetary_policy_report_2024_03 | 40 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| fed_monetary_policy_report_2024_03 | 50 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| fed_monetary_policy_report_2024_03 | 68 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| fed_monetary_policy_report_2024_03 | 70 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| fed_monetary_policy_report_2024_03 | 71 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| fed_survey_consumer_finances_2022 | 3 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| fed_survey_consumer_finances_2022 | 23 | p23_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_survey_consumer_finances_2022 | 23 | p23_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_survey_consumer_finances_2022 | 23 | p23_t3 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_survey_consumer_finances_2022 | 23 | p23_t4 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_survey_consumer_finances_2022 | 25 | p25_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_survey_consumer_finances_2022 | 25 | p25_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_survey_consumer_finances_2022 | 25 | p25_t3 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_survey_consumer_finances_2022 | 25 | p25_t4 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_survey_consumer_finances_2022 | 29 | p29_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_survey_consumer_finances_2022 | 29 | p29_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_survey_consumer_finances_2022 | 29 | p29_t3 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_survey_consumer_finances_2022 | 29 | p29_t4 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_survey_consumer_finances_2022 | 33 | p33_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_survey_consumer_finances_2022 | 33 | p33_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_survey_consumer_finances_2022 | 33 | p33_t3 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_survey_consumer_finances_2022 | 33 | p33_t4 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_survey_consumer_finances_2022 | 33 | p33_t5 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_survey_consumer_finances_2022 | 33 | p33_t6 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_survey_consumer_finances_2022 | 33 | p33_t7 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| fed_survey_consumer_finances_2022 | 4 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| fed_survey_consumer_finances_2022 | 6 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| fed_survey_consumer_finances_2022 | 10 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| fed_survey_consumer_finances_2022 | 16 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| fed_survey_consumer_finances_2022 | 34 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| fed_survey_consumer_finances_2022 | 38 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| fed_survey_consumer_finances_2022 | 57 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| oecd_economic_outlook_116_annex | 3 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| oecd_economic_outlook_116_annex | 6 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| oecd_economic_outlook_116_annex | 7 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| oecd_economic_outlook_116_annex | 22 | p22_t20 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| oecd_economic_outlook_116_annex | 47 | p47_t13 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| oecd_economic_outlook_116_annex | 49 | p49_t15 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| oecd_economic_outlook_116_annex | 60 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| oecd_economic_outlook_116_annex | 61 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| oecd_economic_outlook_116_annex | 62 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| oecd_economic_outlook_116_annex | 63 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| oecd_economic_outlook_116_annex | 64 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| treasury_monthly_statement_2024_06 | 4 | p4_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| treasury_monthly_statement_2024_06 | 4 | p4_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| treasury_monthly_statement_2024_06 | 4 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| treasury_monthly_statement_2024_06 | 6 | p6_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| treasury_monthly_statement_2024_06 | 7 | p7_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| treasury_monthly_statement_2024_06 | 8 | p8_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| treasury_monthly_statement_2024_06 | 2 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| treasury_monthly_statement_2024_06 | 40 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| usda_agricultural_prices_2025_09 | 3 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_agricultural_prices_2025_09 | 4 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_agricultural_prices_2025_09 | 51 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 8 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 9 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 10 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 11 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 12 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 13 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 14 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 15 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 16 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 17 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 18 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 19 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 20 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 21 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 22 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 23 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 24 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 25 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 26 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 27 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 28 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 29 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 30 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 33 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 34 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 35 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 36 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 37 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| usda_wasde_2026_06 | 39 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| worldbank_commodity_markets_2025_04 | 5 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| worldbank_commodity_markets_2025_04 | 11 | p11_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 11 | p11_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 15 | p15_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 15 | p15_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 15 | p15_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 15 | p15_t3 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 15 | p15_t4 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 15 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| worldbank_commodity_markets_2025_04 | 23 | p23_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 25 | None | RECOVERED: lines strategy found no usable table; text-strategy fallback recovered 1 table(s) — borderless/dot-leader layout |
| worldbank_commodity_markets_2025_04 | 26 | p26_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 28 | p28_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 31 | p31_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 31 | p31_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 31 | p31_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 31 | p31_t3 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 31 | p31_t4 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 31 | p31_t5 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 31 | p31_t6 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 31 | p31_t7 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 31 | p31_t8 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 31 | p31_t9 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 34 | p34_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 35 | p35_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 35 | p35_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 35 | p35_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 38 | p38_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 38 | p38_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 38 | p38_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 38 | p38_t3 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 39 | p39_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 39 | p39_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 41 | p41_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 41 | p41_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 41 | p41_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 41 | p41_t3 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 47 | p47_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 60 | p60_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 60 | p60_t1 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 60 | p60_t2 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 60 | p60_t3 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 60 | p60_t4 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 63 | p63_t0 | extract_tables() returned an empty/all-blank table (lines strategy; usually a chart's axes/gridlines detected as a table) |
| worldbank_commodity_markets_2025_04 | 2 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| worldbank_commodity_markets_2025_04 | 8 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| worldbank_commodity_markets_2025_04 | 22 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| worldbank_commodity_markets_2025_04 | 50 |  | no extractable text — likely scanned/image-only page (OCR not run) |
| worldbank_commodity_markets_2025_04 | 67 |  | no extractable text — likely scanned/image-only page (OCR not run) |
