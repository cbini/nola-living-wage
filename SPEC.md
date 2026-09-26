# New Orleans Living Wage Capacity: Preliminary Spec

**Status:** draft v0.1, 2026-09-26. Hand-off spec for implementation in Claude Code.

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
| MIT Living Wage Calculator | Hourly thresholds for 12 household types, Orleans Parish (FIPS 22071) | Current year only | Scrape `livingwage.mit.edu/counties/22071`; store a dated snapshot in the repo |
| ACS 5-year PUMS, 2020–2024 (released 2026-03-05) | Person and household microdata: wages, hours, weeks, industry, place of work | Person, with household link (`SERIALNO`) | Census API or bulk CSV. Pull the **LA and MS** person and household files, since Mississippi commuters appear only in the MS file |
| BEA CAGDP2 | GDP by county and industry, current dollars | County × NAICS sector × year | BEA API (free key) |
| BEA CAINC6N | Compensation of employees by industry, place of work | County × NAICS sector × year | BEA API |
| BEA SAGDP (state components) | Taxes on production and imports, compensation, and GOS by industry | State × industry × year | BEA API. Used only to model county GOS (§6) |
| BLS CPI-U, South urban (CUUR0300SA0) | Price deflator | Monthly/annual | BLS API or flat file |

**Snapshot for reference (fetched 2026-09-26, MIT data updated 2026-02-15), hourly, Orleans Parish:**

| Household | 0 kids | 1 kid | 2 kids | 3 kids |
|---|---|---|---|---|
| 1 adult | **$20.29** (floor) | $34.36 | $43.11 | $53.47 |
| 2 adults, 1 working | $28.86 | $34.40 | $36.97 | $42.60 |
| 2 adults, both working (per worker) | $14.43 | $19.89 | $23.77 | $28.45 |

MIT defines these as full-time rates at 2,080 hours per year. The pipeline scrapes them; do not hardcode this table.

## 4. Worker universe and wage construction

**Filter (person file):**
- Place of work state `POWSP` = 22 and place-of-work PUMA `POWPUMA` = Orleans Parish. **Verify the code(s)** against the PUMS data dictionary and the place-of-work PUMA equivalency file. Orleans should be identifiable as its own place-of-work area, but confirm it for each PUMA vintage in the file (see §8).
- Worked in the past 12 months, with `WAGP` > 0, `WKHP` > 0, and `WKWN` > 0.
- Class of worker `COW` in wage/salary categories (private for-profit, nonprofit, local/state/federal government). Exclude self-employed and unpaid family workers from the wage gap and report them separately as a count.

**Hourly wage:** `wage_hr = WAGP × (ADJINC / 1e6) / (WKHP × WKWN)`, then inflated by CPI-U South to the MIT price year.
- The PUMS README says `ADJINC` brings all five survey years to 2024 dollars. MIT's February 2026 update is treated as 2025 prices; **confirm from MIT's methodology page**, then carry wages forward from 2024 to that year.
- Keep the direction consistent: move wages to MIT's year, not MIT back to 2024. That way results read in today's dollars.

**Outlier rule:** Flag hourly wages below $2 or above $500 and exclude them from the main run. Report how many were dropped, and run a sensitivity check with them left in. These come from misreported hours or weeks, not real pay.

**Weights:** Use `PWGTP` for all estimates. Compute standard errors with the 80 replicate weights (`PWGTP1`–`PWGTP80`) using the successive-difference formula: SE = sqrt(4/80 × Σ(rep − full)²). Every headline number ships with a 90% margin of error.

## 5. Gap calculations

**Floor gap (Q1):** For each worker, `gap_i = max(0, floor − wage_hr_i) × WKHP_i × WKWN_i`. Aggregate with weights:
- workers below the floor (count, share)
- total annual gap in dollars
- mean shortfall per affected worker, in $/hr and $/yr

Break out each by industry (NAICS sector crosswalked from `NAICSP`/`INDP` to BEA's CAGDP2 lines) and by class of worker (public vs. private vs. nonprofit). Note that Orleans Parish government is itself an employer in this set.

**Household-type comparison (Q2):** Attach each worker to a MIT household type, then compare their wage with that type's threshold.
- **Unit:** the worker's family within the PUMS household: the reference person, their spouse or unmarried partner, and their own children under 18 (`RELSHIPP`, `AGEP`). Roommates and other adult relatives form their own units.
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
| Wage and salary disbursements | CAINC5N | Closest match to `WAGP` |
| **Gross operating surplus (modeled)** | GDP − compensation − estimated taxes | The pool a raise would come out of |

**GOS model:** County GOS is not published. Estimate it by industry as county GDP − county compensation − (county GDP × the state ratio of taxes on production and imports to GDP for that industry). GOS includes depreciation and proprietors' income, so it overstates distributable profit. Report it as an upper bound and also run a lower-bound variant that subtracts depreciation, using the national consumption-of-fixed-capital share by industry from the NIPA fixed-asset tables.

**Headline ratios, total and by industry:**
- gap ÷ GDP
- gap ÷ compensation (percent raise to the total wage bill)
- gap ÷ GOS (upper and lower bound)

An industry fails the self-funding test when its gap exceeds its own GOS. Report those industries explicitly. Hospitality is the likely case, and the spec expects the analysis to say so rather than bury it.

**Year alignment:** The PUMS pools 2020–2024. Compare against the 2020–2024 BEA average in the same dollars. The COVID years (2020–21) distort hospitality, so also run a 2022–2024 comparison. PUMS single years are available through `ADJINC`/year of survey, but single-year samples are thin at parish level; flag the resulting MOEs.

## 7. Sensitivities

Run each as a parameter in one config file, never hand-edited in code:
1. **Price pass-through:** a share *p* of the gap is passed into local prices, which raises the MIT threshold by *p* × gap ÷ local consumption spending. Iterate until it converges; default *p* = 0.5, and also run 0 and 1. Local consumption is approximated by Orleans Parish personal consumption (BEA CAPCE is state-level; allocate by personal income share and document it).
2. **Outliers included.**
3. **Hours rule:** actual hours (default) vs. requiring each worker to earn floor × 2,080 per year.
4. **Out-of-state commuters dropped** (LA file only), to show how much the MS file changes things.
5. **Pandemic years dropped** (2022–2024 only).

## 8. Known risks and things to verify first

- **Place-of-work PUMA vintage.** The 2020–2024 file mixes survey years coded to 2010 PUMAs and 2020 PUMAs. Confirm how `POWPUMA` is coded across years and that Orleans Parish maps cleanly in both. If it doesn't, stop and report before building further.
- **Industry crosswalk.** PUMS `NAICSP` codes are at mixed detail levels and BEA uses sector lines; build an explicit crosswalk table in the repo and test that every PUMS code maps exactly once.
- **Disclosure suppression.** BEA marks some county-industry cells "(D)". Carry them as unknown, not zero, and report how much GDP falls in suppressed cells.
- **Tips and cash income** are in `WAGP` only as reported. Note the likely undercount for hospitality.
- **Survey vs. administrative totals.** Sum weighted `WAGP` for the universe and compare with CAINC5N wage disbursements. A large mismatch (say beyond ±15%) needs explaining before any ratio is published.

## 9. Repo layout

```
nola-living-wage/
├── SPEC.md                 # this file
├── README.md               # how to reproduce in three commands
├── pyproject.toml          # uv-managed; python ≥3.12; duckdb, polars, httpx, pyyaml, pytest
├── config.yaml             # years, floor household type, thresholds, sensitivity params
├── .env.example            # CENSUS_API_KEY, BEA_API_KEY, BLS_API_KEY
├── src/nola_lw/
│   ├── fetch/              # one module per source; writes to data/raw/ with a manifest (url, date, sha256)
│   ├── build/              # universe, wages, household types, crosswalk
│   ├── analysis/           # gaps, capacity, sensitivities, replicate-weight SEs
│   └── report/             # tables to CSV + a markdown results summary with charts
├── crosswalks/             # naicsp_to_bea.csv, powpuma_orleans.csv (committed, hand-checked)
├── data/
│   ├── raw/                # gitignored; populated by fetch
│   ├── snapshots/          # committed: MIT scrape and small reference tables
│   └── out/                # gitignored except final tables
└── tests/                  # gap math on synthetic workers; crosswalk coverage; SE formula
```

**Reproducibility rules:**
- `make all` (or `uv run nola-lw all`) runs fetch → build → analysis → report from nothing.
- Every raw download is recorded in a manifest with URL, fetch date, and hash.
- The MIT page changes each year, so the snapshot used is committed and dated. A rerun uses the committed snapshot unless `--refresh-mit` is passed.
- No numbers are typed into code; all constants come from `config.yaml` or fetched data.

## 10. Deliverables

1. `data/out/results.md`: a headline paragraph, then the tables below, each with MOEs:
   - workers below the floor
   - total gap
   - gap vs. GDP, compensation, and GOS
   - the industry table with the self-funding test
   - the 12-cell household table
   - the sensitivity table
2. CSVs of every table.
3. Two charts: gap vs. GOS by industry (bar), and the distribution of hourly wages with the floor marked.

## 11. Build order for Claude Code

1. Scaffold the repo, config, and fetchers; pull all sources.
2. **Checkpoint:** verify the Orleans `POWPUMA` code(s) and the survey-vs-BEA wage total (§8). Report before continuing.
3. Build the worker universe and hourly wages; test them.
4. Calculate the floor gap and replicate-weight SEs.
5. Build household typing and the 12-cell table.
6. Pull BEA, build the crosswalk, model GOS, and compute capacity ratios.
7. Run the sensitivities, then the report.

## 12. Open decisions

- Is a family unit (§5) the right match for MIT's household, or should the whole PUMS household be used?
- Should commuters living outside Orleans be compared with their home parish's MIT thresholds in the household table? The default uses Orleans thresholds for everyone, since the question is about jobs in Orleans.
- Should public-sector workers be kept in the capacity test? Their raise is funded by taxes, not GOS. The default keeps them in the counts but reports the capacity test with and without them.
