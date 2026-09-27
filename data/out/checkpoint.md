# Checkpoint report (SPEC §11 step 2)

## 1. Orleans POWPUMA code(s) by vintage

Data dictionary fields (every PUMA-type variable in the file):

- `PUMA`: Public use microdata area code (PUMA) based on 2020 Census definition (areas with population of 100,000 or more, use with STATE for unique code)
- `POWPUMA`: Place of work public use microdata area code (POWPUMA) based on 2020 Census definitions
- `POWSP`: Place of work - State or foreign country recode

Weighted persons with `POWSP` = 022, by `POWPUMA` and survey year (5-year weights):

| POWPUMA | 2020 | 2021 | 2022 | 2023 | 2024 |
|---|---|---|---|---|---|
| 00100 | 20166 | 20750 | 21833 | 23016 | 22683 |
| 00200 | 11566 | 12877 | 13278 | 12096 | 12722 |
| 00300 | 12434 | 11071 | 13162 | 11929 | 12788 |
| 00400 | 13990 | 13535 | 14195 | 14893 | 14965 |
| 00500 | 6654 | 6713 | 8613 | 7869 | 8298 |
| 00600 | 4763 | 6043 | 6290 | 6159 | 6294 |
| 00700 | 16513 | 15882 | 16227 | 15256 | 17376 |
| 00890 | 26070 | 25285 | 27255 | 26170 | 27028 |
| 01000 | 7491 | 7159 | 6267 | 6637 | 6855 |
| 01100 | 5381 | 6330 | 5902 | 5723 | 5587 |
| 01200 | 25726 | 29483 | 27713 | 30264 | 29130 |
| 01300 | 9744 | 7118 | 8849 | 8972 | 7864 |
| 01400 | 9525 | 8836 | 9873 | 9890 | 10334 |
| 01500 | 46671 | 49600 | 56159 | 53777 | 54351 |
| 01600 | 11183 | 9423 | 11519 | 9867 | 10860 |
| 01700 | 4983 | 6495 | 8889 | 7755 | 7641 |
| 01800 | 12040 | 12539 | 12745 | 12962 | 14569 |
| 01900 | 11048 | 10924 | 9469 | 10036 | 11100 |
| 02000 | 7952 | 7620 | 8676 | 7610 | 8172 |
| 02100 | 13465 | 14009 | 13723 | 15225 | 14959 |
| 02200 | 17797 | 21856 | 21226 | 21940 | 23096 |
| 02390 | 40462 | 43639 | 42743 | 42844 | 42950 |
| 02400 | 43117 | 40810 | 44590 | 44994 | 45875 |

2020 residence PUMAs in the state grouped by their first three digits + "00", with their counties from the 2020 tract-to-PUMA file, and whether that code occurs as a `POWPUMA`:

| powpuma_prefix | pumas | counties | code_in_data |
|---|---|---|---|
| 00100 | 00101 00102 | 017 | True |
| 00200 | 00200 | 015 119 | True |
| 00300 | 00300 | 013 027 031 061 069 081 085 | True |
| 00400 | 00400 | 073 | True |
| 00500 | 00500 | 021 035 041 049 065 067 083 107 111 123 | True |
| 00600 | 00600 | 009 025 029 043 059 127 | True |
| 00700 | 00700 | 079 115 | True |
| 00800 | 00801 | 003 011 019 | False |
| 00900 | 00901 | 019 023 053 | False |
| 01000 | 01000 | 039 097 | True |
| 01100 | 01100 | 001 113 | True |
| 01200 | 01201 01202 | 055 | True |
| 01300 | 01300 | 045 099 | True |
| 01400 | 01400 | 037 047 077 121 125 | True |
| 01500 | 01501 01502 01503 01504 | 033 | True |
| 01600 | 01600 | 005 | True |
| 01700 | 01700 | 063 091 | True |
| 01800 | 01800 | 105 117 | True |
| 01900 | 01900 | 089 093 095 | True |
| 02000 | 02000 | 007 057 | True |
| 02100 | 02100 | 101 109 | True |
| 02200 | 02201 02202 | 103 | True |
| 02300 | 02301 02302 02303 | 051 | False |
| 02400 | 02401 02402 02403 | 071 | True |
| 02500 | 02501 | 051 075 087 | False |

`POWPUMA` codes in the data that do not follow the prefix pattern: ['00890', '02390']. Each sits where prefix groups share a county (POWPUMAs must follow county lines), so Census merged them — e.g. a county split across PUMA groups. This does not affect Orleans, whose PUMA group contains no other county.

- `02400`: residence PUMAs ['02401', '02402', '02403'] lie only in county 071: **True**; they cover every Orleans PUMA ['02401', '02402', '02403']: **True**; present in every survey year: **True**.

**Verdict: CONFIRMED** — config `orleans.powpuma` = ['02400']. There is one `POWPUMA` field, labelled as 2020 Census definitions, and the same codes appear in every survey year, so Census has coded all five years to 2020 POWPUMAs (no 2010 vintage in this file). Caveat: Census's official 2020 POWPUMA composition file was not reachable from this environment (usa.ipums.org is blocked; www2.census.gov carries only the tract-to-PUMA file), so the PUMA-to-POWPUMA link rests on the 3-digit naming convention, checked against the counts above.

## 2. Survey WAGP vs. BEA wages and salaries (place of work)

Survey (avg year, 2024$, ADJINC applied): $12,744,292,960 ± 417,711,003 (90% MOE), 9,627 person records.

CAINC5N line 50, nominal dollars:

| year | value | flag |
|---|---|---|
| 2020 | 11,644,740,000 |  |
| 2021 | 12,261,593,000 |  |
| 2022 | 13,218,330,000 |  |
| 2023 | 13,650,647,000 |  |
| 2024 | 14,206,017,000 |  |

**BLOCKED: missing BLS CPI CUUR0300SA0 to put BEA 2020–2023 in 2024 dollars, so the % difference is not computed.**
## 3. MIT stated price basis

Snapshot `mit_counties_22071_2026-09-27.csv`: MIT's methodology page says figures are adjusted to **December 2025 dollars**. Config `cpi.target` = `2025-12`. Floor (a1_w1_c0) = $20.29/hr.

## 4. GDP in BEA "(D)" cells; suppressed CAINC6N cells

CAGDP2, Orleans, dollars. Residual = total − Σ top-level sectors; ±$2k is BEA rounding:

| year | total | disclosed | n_suppressed | suppressed_lines | residual | share |
|---|---|---|---|---|---|---|
| 2020 | 23,249,364,000 | 23,249,364,000 | 0 |  | 0 | 0.0000% |
| 2021 | 25,535,608,000 | 25,535,607,000 | 0 |  | 1,000 | 0.0000% |
| 2022 | 28,447,528,000 | 28,447,526,000 | 0 |  | 2,000 | 0.0000% |
| 2023 | 29,678,170,000 | 29,678,168,000 | 0 |  | 2,000 | 0.0000% |
| 2024 | 30,835,434,000 | 30,835,436,000 | 0 |  | -2,000 | -0.0000% |

CAINC6N, Orleans, cell counts by year:

| year | cells | suppressed | D | NA | zero_values |
|---|---|---|---|---|---|
| 2020 | 118 | 18 | 17 | 1 | 2 |
| 2021 | 118 | 17 | 16 | 1 | 2 |
| 2022 | 118 | 26 | 25 | 1 | 2 |
| 2023 | 118 | 27 | 26 | 1 | 3 |
| 2024 | 118 | 34 | 33 | 1 | 2 |

Total suppressed CAINC6N cells 2020–2024: **122** ((D) 117, (NA) 5).

## 5. NAICSP codes by survey year (Orleans place-of-work universe)

| year | records | distinct codes | codes not in every year |
|---|---|---|---|
| 2020 | 1,562 | 178 | 111 114 211 2121 2122 221MP 3113 3116 3121 3221 3261 3262M 32711 32712 3327 33641M2 3369 4232 4234 4237 4238 42393 4244 4245 4247 424M 4251 42S 4412 44414 4442 44513 4452 4453 4551 4572 4582 45921 4593 45941 45942 487 51311 5131Z 5132 5321 53M 5414 62131 6243 7112 7115 71395 811192 812112 8129 81393 92811P2 92811P7 |
| 2021 | 2,151 | 182 | 111 112 115 211 2212P 3114 3116 311811 311M1 3121 3132Z 315M 3221 3252 32711 331M 332M 33311 3331M 3333 33641M2 336M 337 3MS 4232 4234 4236 4238 4239Z 4241 4243 4247 4249Z 424M 4412 44414 44513 4452 4491 4571 4582 4591M 45921 4593 45942 487 5131Z 5182 5321 532M2 53M 5414 6222 6243 7111 7112 7115 71395 811192 8114 812112 8129 81393 |
| 2022 | 2,049 | 177 | 115 211 2122 22S 3113 311811 311M1 3121 315M 3211 3252 3253 3272 3279 3327 332M 332MZ 33311 3333 3369 336M 3MS 4231 4234 4236 4237 4238 4239Z 4243 4244 4249Z 424M 44414 44513 4453 4491 4551 4571 4572 4582 45914 4591M 4593 45941 45942 486 51311 5131Z 5132 5182 6222 7111 7112 7115 721M 811192 8114 812112 |
| 2023 | 1,859 | 180 | 111 211 2122 221MP 3113 3114 3116 311811 314Z 3211 3219ZM 3221 3252 3255 3256 3261 327M 3313 331M 332M 3341 33641M2 336M 337 3MS 4231 4237 4238 4244 4249Z 424M 4251 42S 4412 4442 4452 4453 4491 4551 4571 4582 4591M 45921 487 5122 51311 5132 5182 51929 5321 532M2 53M 5414 62132 6222 6243 7111 71395 721M 8129 92811P2 |
| 2024 | 2,006 | 181 | 111 2212P 221MP 22S 3113 3114 311811 3121 3211 3219ZM 3222M 3241M 3256 3261 327M 331M 3321 3327 33641M2 337 3MS 4235 4236 4237 4239Z 4241 4244 4247 44414 44513 4452 4453 4491 4551 4571 45913 4591M 45921 4593 45942 487 5122 51311 5131Z 5132 5182 532M2 53M 5414 62132 6222 7111 7112 7115 71395 721M 811192 8112 812112 8129 81393 92811P2 |

119 codes appear in every year. The crosswalk (§11.6) must cover the union: 234 codes.

Dictionary label: "North American Industry Classification System (NAICS) recode for 2023 and later based on 2022 NAICS codes". Codes in the data but not in the dictionary's value list, by year: 2020: none; 2021: none; 2022: none; 2023: none; 2024: none.

