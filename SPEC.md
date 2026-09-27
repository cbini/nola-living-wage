# New Orleans Living Wage Capacity: Preliminary Spec

**Status:** draft v0.2, 2026-09-26. Hand-off spec for implementation in Claude Code. v0.2 resolves the open decisions (§12) and corrects several source details found while resolving them.

## 1. Questions

1. **Who falls short?** How many people who work in Orleans Parish earn less than the MIT living wage for one adult with no children? The rate is applied as an hourly floor to every worker, regardless of household.
2. **How far short?** Measured against each worker's own household-type MIT threshold, how many fall short, and by how much?
3. **Can the economy carry it?** What would it cost to raise every worker to the floor? How does that cost compare with the parish's output: GDP, employee compensation, and estimated profits (gross operating surplus)? Answer overall and industry by industry.

The argument being tested is that every worker deserves at least the floor and that the local economy produces enough to pay it. Wherever a result undercuts that argument, the pipeline reports it plainly rather than hiding it.

## 2. Core design principle: place of work

GDP and compensation are counted where the work happens, so every worker measure is too. The worker universe is **people whose job is in Orleans Parish**, wherever they live. That includes commuters from Jefferson, St. Tammany, and Mississippi, and excludes residents who work outside the parish. Mixing residence-based and workplace-based numbers is the main way this analysis could be attacked, so it must not happen anywhere.

## 3. Data sources

| Source | What | Grain | Access |
|---|---|---|---|
| MIT Living Wage Calculator | Hourly thresholds for 12 household types, Orleans Parish (FIPS 22071) and the New Orleans–Metairie metro (CBSA 35380, sensitivity only) | Current year only | Scrape `livingwage.mit.edu/counties/22071` and `/metros/35380`; store dated snapshots in the repo |
| ACS 5-year PUMS, 2020–2024 (released 2026-03-05) | Person and household microdata: wages, hours, weeks, industry, place of work | Person, with household link (`SERIALNO`) | Bulk CSV, no key needed. Pull the **LA and MS** person and household files, plus the person file for **every other state**. From each other state, keep every person in any household with a member whose `POWSP` = 22, and discard the rest of the file. This makes the worker universe include all out-of-state commuters (§4) with their household members |
| BEA CAGDP2 | GDP by county and industry, current dollars | County × NAICS sector × year | BEA API (free key) |
| BEA CAINC6N | Compensation of employees by industry, place of work | County × NAICS sector × year | BEA API |
| BEA CAINC5N | Wage and salary disbursements by industry, place of work | County × NAICS sector × year | BEA API. Used for the survey-vs-admin check (§8) and the §6 comparison |
| BEA SAPCE | Personal consumption expenditures, by state of residence | State × year | BEA API. Used only for the §7 pass-through bound |
| BEA CAINC1 / SAINC1 | Personal income, by place of residence | County / state × year | BEA API. Used only to allocate SAPCE to Orleans (§7) |
| BEA SAGDP2/3/4/7 (state) | GDP; taxes on production and imports **less subsidies** (SAGDP3); compensation (SAGDP4); GOS (SAGDP7) by industry | State × industry × year | BEA API. Used to model county GOS (§6), with SAGDP7 used to validate the method |
| BLS CPI-U, South urban (CUUR0300SA0) | Price deflator | Monthly/annual | BLS API or flat file |

**Snapshot for reference (fetched 2026-09-26, MIT data updated 2026-02-15), hourly, Orleans Parish:**

| Household | 0 kids | 1 kid | 2 kids | 3 kids |
|---|---|---|---|---|
| 1 adult | **$20.29** (floor) | $34.36 | $43.11 | $53.47 |
| 2 adults, 1 working | $28.86 | $34.40 | $36.97 | $42.60 |
| 2 adults, both working (per worker) | $14.43 | $19.89 | $23.77 | $28.45 |

MIT defines these as full-time rates at 2,080 hours per year. The pipeline scrapes them; do not hardcode this table.

## 4. Worker universe and wage construction

**Filter (person file):** the universe is every PUMS person, from any state of residence, meeting all of the following. Every state's residents come from the bulk files (§3). The universe drives Q1 and Q3; residence and household matter only for Q2.
- Place of work state `POWSP` = 22 and place-of-work PUMA `POWPUMA` = Orleans Parish. **Verify the code(s)** against the PUMS data dictionary and the place-of-work PUMA equivalency file. Orleans should be identifiable as its own place-of-work area, but confirm it for each PUMA vintage in the file (see §8).
- Worked in the past 12 months, with `WAGP` > 0, `WKHP` > 0, and `WKWN` > 0.
- Class of worker `COW` in wage/salary categories (private for-profit, nonprofit, local/state/federal government). Exclude self-employed and unpaid family workers from the wage gap and report them separately as a count.

**Hourly wage:** `wage_hr = WAGP × (ADJINC / 1e6) / (WKHP × WKWN)`, then inflated by CPI-U South to the MIT price year.
- The PUMS README says `ADJINC` brings all five survey years to 2024 dollars. MIT's methodology page (checked 2026-09-26) says all 2026 figures are in **December 2025 dollars**. Carry wages forward by CPI-U South, December 2025 ÷ 2024 annual average. Use December 2025, not the 2025 annual average, because it matches MIT's stated basis exactly. The annual average is lower, so using it would understate wages relative to the thresholds and inflate the gap. Re-check the stated price basis at the §11 step 2 checkpoint.
- Keep the direction consistent: move wages to MIT's year, not MIT back to 2024. That way results read in today's dollars.

**Outlier rule:** Flag hourly wages below $2 or above $500 and exclude them from the main run. Report how many were dropped, and run a sensitivity check with them left in. These come from misreported hours or weeks, not real pay.

**Weights:** Use `PWGTP` for all estimates. Compute standard errors with the 80 replicate weights (`PWGTP1`–`PWGTP80`) using the successive-difference formula: SE = sqrt(4/80 × Σ(rep − full)²). Every headline number ships with a 90% margin of error.

## 5. Gap calculations

**Floor gap (Q1):** For each worker, `gap_i = max(0, floor − wage_hr_i) × WKHP_i × WKWN_i`. Aggregate with weights:
- workers below the floor (count, share)
- total annual gap in dollars
- mean shortfall per affected worker, in $/hr and $/yr

Break out each by industry (BEA CAGDP2 lines; see the crosswalk rule in §8) and by class of worker (public vs. private vs. nonprofit). Note that Orleans Parish government is itself an employer in this set.

**Commuter leakage:** report the share of below-floor workers, and of total gap dollars, going to people who live outside Orleans, split into other Louisiana parishes and out of state. Commuters stay in every gap and capacity calculation. Their work is part of Orleans GDP (§2), and this breakdown only shows where the raise money would be spent.

**Household-type comparison (Q2):** Attach each worker to a MIT household type, then compare their wage with that type's threshold.
- **Unit (decided, §12):** the worker's family unit within the PUMS household: the reference person, their spouse or unmarried partner, and their own children under 18 (`RELSHIPP`, `AGEP`). Subfamilies are split out as their own units using `SFN`/`SFR`; for example, a single parent and child living with the parent's parents form a 1-adult, 1-child unit. Roommates and other adult relatives form their own single-adult units. This matches MIT's assumption of one pooled family budget.
- **Thresholds:** Orleans MIT thresholds for every worker, wherever they live. Metro thresholds are a §7 sensitivity.
- **Coverage:** every commuter's household members are retained from the bulk person files (§3), so all workers are typed, wherever they live.
- **Adults:** 1 or 2. **Children:** capped at 3 (flag households with more).
- **Working adults:** 2 if both adults have `WAGP` > 0 or self-employment income; otherwise 1.
- **Output:** a 12-cell table showing workers, the share below their own-household threshold, and the total gap in each cell. Report a side-by-side view: below the floor vs. below their own threshold.
- **Caveat to report:** MIT's thresholds assume full-time work. A part-time worker can be above the hourly floor and still far short in annual income. Also report an annual version: earnings vs. threshold × 2,080.

## 6. Capacity comparison (Q3)

Put the floor gap next to these parish totals for the matching year(s), all at place of work and in the same dollars:

| Measure | Source | Note |
|---|---|---|
| GDP | CAGDP2 | Upper bound on everything |
| Employee compensation | CAINC6N | Includes benefits, not just wages |
| Wage and salary disbursements | CAINC5N line 50 (equal to CAINC6N line 5; checked 2026-09-27) | Closest match to `WAGP` |
| **Gross operating surplus (modeled)** | GDP − compensation − estimated taxes | The pool a raise would come out of |

**GOS model:** County GOS is not published. Estimate it by industry as county GDP − county compensation − (county GDP × the state ratio of taxes on production and imports **less subsidies** (SAGDP3) to GDP for that industry). Using the net figure keeps the accounting identity GDP = compensation + net taxes + GOS. **Validate the method on Louisiana:** applying the same formula to state data must reproduce SAGDP7 GOS by industry, within rounding. GOS includes depreciation and proprietors' income, so it overstates distributable profit. Report it as an upper bound and also run a lower-bound variant that subtracts depreciation, using the national consumption-of-fixed-capital share by industry from the NIPA fixed-asset tables.

**Headline ratios, total and by industry:**
- gap ÷ GDP
- gap ÷ compensation (percent raise to the total wage bill)
- gap ÷ GOS (upper and lower bound)

An industry fails the self-funding test when its gap exceeds its own GOS. Report those industries explicitly. Hospitality is the likely case, and the spec expects the analysis to say so rather than bury it.

**Public sector (decided, §12):** government workers are in every count, the total gap, gap ÷ GDP, and gap ÷ compensation. BEA government GOS is only consumption of fixed capital, so a government line always "fails" the self-funding test, and that failure is an accounting artifact. The GOS test is therefore shown two ways, **with equal prominence**: (a) private and nonprofit gap ÷ private-industry GOS, and (b) all-sector gap ÷ total GOS. The government gap is also reported as a percent raise to government compensation, which is a public-budget cost. The industry self-funding table excludes the government line from the pass/fail column but shows its gap and payroll share.

**Year alignment (decided, §12):** The headline is the published 2020–2024 pool, compared against the 2020–2024 BEA average in the same dollars. The COVID years (2020–21) distort hospitality, so a **2022–2024 column appears alongside the headline in the main tables**, not only in the sensitivity table. If the two differ by more than their MOEs, the headline paragraph says so. The survey year comes from the first four characters of `SERIALNO`. On a year subset, 5-year weights sum to an average year's population over only the included years, so counts and dollar totals are rescaled by 5 ÷ (years included); shares and ratios need no rescaling. Replicate weights are rescaled the same way. The 2022–2024 PUMS numbers are compared with the 2022–2024 BEA average.

## 7. Sensitivities

Run each as a parameter in one config file, never hand-edited in code:
1. **Price pass-through:** a share *p* of the gap is passed into local prices, which raises the MIT threshold by *p* × gap ÷ spending base. Iterate until it converges; default *p* = 0.5, and also run 0 and 1. The spending base is reported as **two bounds (decided, §12)**:
   - *Large price effect:* Orleans residents' consumption = Louisiana SAPCE × (Orleans CAINC1 personal income ÷ Louisiana SAINC1). This is residence-based, used here only as a labeled allocator and never compared with worker measures. It leaves out commuter and tourist spending at Orleans businesses, so it overstates the price effect.
   - *Small price effect:* Orleans GDP (CAGDP2, place of work). It spreads the cost over all output, including goods sold into national markets whose prices can't rise locally, so it understates the price effect.
2. **Outliers included.**
3. **Hours rule:** actual hours (default) vs. requiring each worker to earn floor × 2,080 per year.
4. **Out-of-state commuters dropped:** Louisiana residents only, set against the all-state headline.
5. **Pandemic years dropped** (2022–2024 only). This column also appears alongside the headline (§6).
6. **Metro thresholds:** MIT New Orleans–Metairie metro thresholds in place of Orleans thresholds, for every worker.

## 8. Known risks and things to verify first

- **Place-of-work PUMA vintage.** The 2020–2024 file mixes survey years coded to 2010 PUMAs and 2020 PUMAs. Confirm how `POWPUMA` is coded across years and that Orleans Parish maps cleanly in both. If it doesn't, stop and report before building further.
- **Industry crosswalk.** PUMS `NAICSP` codes are at mixed detail levels and BEA uses sector lines. BEA's county tables put **all** public employees on the "Government and government enterprises" line, whatever their activity. So the crosswalk key is (`COW`, `NAICSP`): `COW` 3–5 (local, state and federal) map to the government line, and everyone else maps by `NAICSP`. Nonprofits (`COW` 2) stay in their private industry, as they do in BEA. Build an explicit crosswalk table in the repo and test that every (`COW`, `NAICSP`) pair in the data maps to exactly one BEA line.
- **Mixed NAICS vintages.** The 2024 5-year PUMS API labels `NAICSP` as "for 2023 and later based on 2022 NAICS", so earlier survey years in the pool may carry 2017-based codes. Check this at the checkpoint and make the crosswalk cover every code that appears in any year.
- **Disclosure suppression.** BEA marks some county-industry cells "(D)". Carry them as unknown, not zero, and report how much GDP falls in suppressed cells. **The API returns a suppressed cell as `DataValue` "0" with `NoteRef` "(D)"** (checked 2026-09-27), so the parser must read `NoteRef`. Orleans CAGDP2 has no suppressed sector cells for 2019–2024, but CAINC6N has zero-valued cells at the subsector level, some of them suppressed.
- **Tips and cash income** are in `WAGP` only as reported. Note the likely undercount for hospitality.
- **Survey vs. administrative totals.** Sum weighted `WAGP` for the universe and compare with CAINC5N wage disbursements. A large mismatch (say beyond ±15%) needs explaining before any ratio is published.
- **Source consistency (QA log only).** Log Mississippi and other-state residents' counts, weighted wages and gap separately in `data/out/qa.md`, as a plausibility check on the out-of-state pulls. This split is not reported in `results.md`, because it says nothing about employer pay and the other-state group is likely too small for meaningful MOEs.
- **BEA API limits.** At most 100 requests, 100 MB and 30 errors per minute. Exceeding any of these locks the key out for 1 hour. The fetcher throttles, and treats any `Error` in a response as fatal, never as missing data.
- **POWPUMA labels in the API.** The 2024 5-year API exposes only `POWPUMA` "based on 2020 Census definitions", with no 2010-vintage field. Check at the checkpoint whether the bulk file carries separate 2010 and 2020 fields, or whether Census has recoded all years to 2020 definitions.

## 9. Repo layout

```
nola-living-wage/
├── SPEC.md                 # this file
├── README.md               # how to reproduce in three commands
├── pyproject.toml          # uv-managed; python ≥3.12; duckdb, polars, httpx, pyyaml, pytest
├── config.yaml             # years, floor household type, thresholds, sensitivity params
├── .env.example            # BEA_API_KEY, BLS_API_KEY (optional; BEA key is proxy-held in cloud sessions)
├── src/nola_lw/
│   ├── fetch/              # one module per source; writes to data/raw/ with a manifest (url, date, sha256)
│   ├── build/              # universe, wages, household types, crosswalk
│   ├── analysis/           # gaps, capacity, sensitivities, replicate-weight SEs
│   └── report/             # tables to CSV + a markdown results summary with charts
├── crosswalks/             # cow_naicsp_to_bea.csv, powpuma_orleans.csv (committed, hand-checked)
├── data/
│   ├── raw/                # gitignored; populated by fetch
│   ├── snapshots/          # committed: MIT scrape and small reference tables
│   └── out/                # gitignored except final tables
└── tests/                  # gap math on synthetic workers; (COW, NAICSP) crosswalk coverage; SE formula
```

**Reproducibility rules:**
- `make all` (or `uv run nola-lw all`) runs fetch → build → analysis → report from nothing.
- Every raw download is recorded in a manifest with URL, fetch date, and hash.
- The MIT page changes each year, so the snapshot used is committed and dated. A rerun uses the committed snapshot unless `--refresh-mit` is passed.
- No numbers are typed into code; all constants come from `config.yaml` or fetched data.

## 10. Deliverables

1. `data/out/results.md`: a headline paragraph, then the tables below, each with MOEs. Main tables show 2020–2024 with a 2022–2024 column alongside:
   - workers below the floor
   - total gap
   - gap vs. GDP, compensation, and GOS (GOS test shown both ways; government gap as a percent of government payroll)
   - the industry table with the self-funding test
   - commuter leakage: share of below-floor workers and gap dollars by residence (Orleans, other LA, out of state)
   - the 12-cell household table
   - the sensitivity table
2. CSVs of every table.
3. Two charts: gap vs. GOS by industry (bar), and the distribution of hourly wages with the floor marked.

## 11. Build order for Claude Code

1. Scaffold the repo, config, and fetchers; pull all sources.
2. **Checkpoint:** verify the Orleans `POWPUMA` code(s) by PUMA vintage, the survey-vs-BEA wage total, MIT's stated price basis, the GDP share in BEA "(D)" cells, and `NAICSP` vintages (§4, §8). Report before continuing.
3. Build the worker universe and hourly wages; test them.
4. Calculate the floor gap and replicate-weight SEs.
5. Build household typing and the 12-cell table.
6. Pull BEA, build the crosswalk, model GOS, and compute capacity ratios.
7. Run the sensitivities, then the report.

## 12. Decisions (resolved 2026-09-26)

| # | Question | Decision | Where applied |
|---|---|---|---|
| a | Family unit or whole PUMS household as MIT's household? | Family unit, with subfamilies (`SFN`/`SFR`) split out as their own units. This matches MIT's single pooled family budget. | §5 |
| b | Home-parish thresholds for commuters? | Orleans thresholds for everyone as the headline. As of 2026-09-26, Orleans's figures are lower than Jefferson's, St. Tammany's and the metro figure (other parishes not checked), so Orleans is the conservative choice. Metro (CBSA 35380) thresholds are a sensitivity. Home-county thresholds per worker are not used: the spread is at most ~7% and residence is known only at PUMA level. Commuters stay in all gap and capacity math, and a leakage breakdown shows where gap dollars go. | §5, §7.6 |
| c | Public-sector workers in the capacity test? | Kept in all counts and in gap ÷ GDP and gap ÷ compensation. The GOS test is shown both ways with equal prominence (private ÷ private GOS; all-sector ÷ total GOS). The government gap is also shown as a percent raise to government payroll. | §6 |
| d | Out-of-state commuters beyond MS? | Bulk person files for every other state, filtered to households with a member whose `POWSP` = 22, so the employer-side universe is complete and every commuter can be household-typed. No Census API key is needed. (This changed from an API pull on 2026-09-27: the Census API is GET-only, so a proxy-held key can't reach it.) | §3, §4, §5, §7.4, §8 (MS vs. other-state split only in the QA log) |
| e | Consumption base for price pass-through? | "CAPCE" does not exist; the source is SAPCE. The spending base is reported as two bounds: resident consumption (SAPCE × CAINC1/SAINC1), which overstates the price effect, and Orleans GDP, which understates it. | §3, §7.1 |
| f | Year window? | The published 2020–2024 pool is the headline, with a 2022–2024 column alongside it in the main tables. Counts and dollar totals are rescaled by 5/3 on the subset. | §6, §7.5 |

**Corrections found while resolving these:** MIT's thresholds are in December 2025 dollars, not "2025 prices" (§4). The industry crosswalk must key on (`COW`, `NAICSP`), not `NAICSP` alone (§8). Two things to check at the checkpoint: `NAICSP` vintages and `POWPUMA` labels in the 5-year file (§8).
