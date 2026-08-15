# Eval set index — `eval/multidoc_expanded.json`

Scan-able index for spot-checking composition without opening all 35 entries.
`X-DOC` = spans 2+ distinct documents · `CONTROL` = same-document (deliberate, see below).

| id | operation | scope | documents spanned | expects |
|---|---|---|---|---|
| X01 | comparison | **X-DOC** | FDIC + BEA-GDP | 1.08, 1.3 |
| X02 | comparison | **X-DOC** | FDIC + FED-MPR | 3.17, 5 |
| X03 | comparison | **X-DOC** | CENSUS-HOUSE + CENSUS-POV | 6.6, 11.5 |
| X04 | comparison | **X-DOC** | EPA + EIA | 319, 3.30 |
| X05 | comparison | **X-DOC** | USDA-AG + WASDE | 137.7, 1,543 |
| X06 | comparison | **X-DOC** | FT900 + BEA-INTL | 92.5, 15.9 |
| X07 | comparison | **X-DOC** | BEA-INC + FDIC | 94.0, 22.5 |
| X08 | comparison | **X-DOC** | EPA + EIA | 38, 13.2 |
| X09 | comparison | **X-DOC** | CENSUS-HOUSE + FDIC | 0.8, 1.08 |
| X10 | comparison | **X-DOC** | EIA + USDA-AG | 2.20, 152.0 |
| X11 | comparison | **X-DOC** | FDIC + BEA-GDP | 4,568, 1.6 |
| X12 | comparison | **X-DOC** | FT900 + BEA-INC | 23.1, 114.1 |
| X13 | aggregation | **X-DOC** | EPA + EIA | 319, 13.2 |
| X14 | aggregation | **X-DOC** | FDIC + CENSUS-HOUSE | 3.17, 65.6 |
| X15 | aggregation | **X-DOC** | WASDE + USDA-AG | 744, 137.7 |
| X16 | aggregation | **X-DOC** | CENSUS-POV + BEA-INC | 37.9, 94.0 |
| X17 | aggregation | **X-DOC** | FT900 + BEA-GDP | 257.6, 1.3 |
| X18 | aggregation | **X-DOC** | EPA + USDA-AG | 27.1, 152.0 |
| X19 | lookup_then_combine | **X-DOC** | FDIC + BEA-GDP | 64.2, 1.3 |
| X20 | lookup_then_combine | **X-DOC** | WASDE + FT900 | 775, 69.4 |
| X21 | lookup_then_combine | **X-DOC** | FDIC + CENSUS-HOUSE | 4.3, 6.6 |
| X22 | lookup_then_combine | **X-DOC** | EIA + FDIC | 3.30, 1.08 |
| X23 | lookup_then_combine | **X-DOC** | EPA + CENSUS-POV | 62, 11.5 |
| X24 | contradiction | **X-DOC** | FDIC + WASDE | 1.08, 1,543 |
| X25 | contradiction | **X-DOC** | CENSUS-POV + CENSUS-HOUSE | 11.5, 65.6 |
| X26 | contradiction | **X-DOC** | EIA + EPA | 13.2, 319 |
| X27 | comparison | control | FDIC | 1.08, 1.36 |
| X28 | comparison | control | CENSUS-HOUSE | 6.6, 0.8 |
| X29 | aggregation | control | FT900 | 92.5, 23.1 |
| X30 | contradiction | control | FDIC | 1.08, 0.61 |
| X31 | comparison | control | WASDE | 1,543, 775 |
| X32 | aggregation | control | USDA-AG | 137.7, 7.2 |
| X33 | lookup_then_combine | control | FDIC | 4,568, 64.2 |
| X34 | comparison | control | EPA | 319, 18 |
| X35 | contradiction | control | EIA | 13.2, 13.4 |

## Totals

- **26 cross-document**, 9 same-document controls, 35 total
- operations: comparison 16, aggregation 8, lookup_then_combine 6, contradiction 5
- distinct documents used: 12 of 16

### Cross-document by operation

- **comparison** — X-DOC: X01, X02, X03, X04, X05, X06, X07, X08, X09, X10, X11, X12 · control: X27, X28, X31, X34
- **aggregation** — X-DOC: X13, X14, X15, X16, X17, X18 · control: X29, X32
- **lookup_then_combine** — X-DOC: X19, X20, X21, X22, X23 · control: X33
- **contradiction** — X-DOC: X24, X25, X26 · control: X30, X35

### Document pair coverage (cross-document questions only)

- EIA + EPA (4)
- BEA-GDP + FDIC (3)
- CENSUS-HOUSE + FDIC (3)
- CENSUS-HOUSE + CENSUS-POV (2)
- USDA-AG + WASDE (2)
- FDIC + FED-MPR (1)
- BEA-INTL + FT900 (1)
- BEA-INC + FDIC (1)
- EIA + USDA-AG (1)
- BEA-INC + FT900 (1)
- BEA-INC + CENSUS-POV (1)
- BEA-GDP + FT900 (1)
- EPA + USDA-AG (1)
- FT900 + WASDE (1)
- EIA + FDIC (1)
- CENSUS-POV + EPA (1)
- FDIC + WASDE (1)

### Why the 9 controls exist

If the fine-tune lifts cross-document questions but leaves controls flat, the gain is specific to *multi-document reasoning* rather than to two-fact extraction in general. Without controls those two explanations are indistinguishable, and we would risk claiming a multi-doc win that was really a generic formatting win.
