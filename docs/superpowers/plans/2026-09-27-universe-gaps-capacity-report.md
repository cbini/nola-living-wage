# Universe, Gaps, Households, Capacity, Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build SPEC §11 steps 3–7: the place-of-work worker universe and hourly wages, the floor gap with replicate-weight MOEs, household typing and the 12-cell table, the BEA capacity comparison with modeled GOS, the six sensitivities, and `results.md` with CSVs and two charts.

**Architecture:** The `nola_lw` package from the first plan gains `build/` (universe, households, crosswalk), `analysis/` (gaps, capacity, sensitivity; `se.py` grows a generic replicate estimator) and `report/`. A single `pipeline.run(cfg)` connects them, and `nola-lw all` becomes fetch → checkpoint → pipeline. Every estimate travels as `(est, se)` and becomes a 90% MOE only in the report.

**Tech Stack:** Python 3.12, uv, polars, httpx, pyyaml, pytest. New dependencies: **matplotlib**, for the two required PNG charts, and **fastexcel**, so polars can read the IPUMS `.xls` file. Use the `dataviz` skill when writing them.

**Spec:** `SPEC.md` v0.2. Also read the checkpoint report `data/out/checkpoint.md` and the first plan `docs/superpowers/plans/2026-09-26-scaffold-fetch-checkpoint.md` (its Findings section).

## Global Constraints

- Place of work only (SPEC §2). The worker universe is `POWSP` = `022` and `POWPUMA` ∈ `orleans.powpuma`, from any state of residence. The residence-based inputs are CAINC1/SAINC1/SAPCE1, used only as the §7.1 allocator, and residence tags, used only for leakage and Q2.
- No numbers in code. Every constant goes in `config.yaml`, and MIT values come from the committed snapshot (SPEC §9).
- BEA suppressed cells (`flag` not null) are **unknown**, never 0. Any sum or ratio that touches one is null and is reported as "suppressed".
- All survey estimates use `PWGTP`, with SE = sqrt(4/80 · Σ(rep − full)²) over `PWGTP1..80`. Every headline number ships with a 90% MOE (`moe_z`).
- Dollars: worker wages and gaps are in MIT's price basis (`cpi.target` = December 2025) through `cpi_factor`. BEA values are converted year by year to the same basis, value_y × CPI(target) ÷ annual_mean(y), before averaging.
- Headline window is the 2020–2024 pool, with 2022–2024 alongside. On a year subset, weights *and* replicate weights are multiplied by (pool years ÷ subset years) = 5/3. Shares and ratios need no rescale.
- Codes (`COW`, `NAICSP`, `PUMA`, `POWPUMA`, `STATE`) stay strings.
- Commit after every task. Push after each completed SPEC §11 step (Tasks 4, 5, 6, 8 and 10).
- Results that cut against the hypothesis (industries failing self-funding, hospitality, the survey-vs-BEA shortfall) are stated plainly in the headline and tables.

## Decisions this plan makes (approving the plan approves these)

1. **Unattached children.** A child under 18 who is neither the reference person's own child nor in a subfamily (for example, a grandchild with no parent present) joins the reference person's family unit. This is MIT's pooled-budget logic, and it raises that unit's threshold, which is the conservative direction.
2. **Adult children.** Own children aged 18 or older, other relatives, roommates and group-quarters persons are each single-adult units (SPEC §5), unless they are in a subfamily.
3. **Working adults.** A two-adult unit counts both adults as working when both have `WAGP` > 0 or `SEMP` ≠ 0 (a loss counts as self-employment).
4. **Depreciation (lower-bound GOS).** Use the national CFC share of GDP by industry: BEA Fixed Assets `FAAt304ESI` (private current-cost depreciation) ÷ SAGDP2 US GDP for the same industry and year, times the county industry GDP. Government GOS is entirely CFC, so the government lower-bound GOS is 0.
5. **Industry grain.** 20 BEA lines that partition the CAGDP2 total: 3, 6, 10, 11, 12, 34, 35, 36, 45, 51, 56, 60, 64, 65, 69, 70, 76, 79, 82, 83. Accommodation and food (79) stays separate from arts (76). Manufacturing stays whole (12).
6. **Suppressed compensation.** Where a CAINC6N industry line is `(D)` (for example Mining in 2024), that industry's compensation, GOS and ratios for any window containing that year are "suppressed". Totals use CAINC6N line 1 and private totals use lines 81 + 90, so they are never blocked.
7. **Pass-through.** It applies to all 12 MIT thresholds, scaled by the same factor. The iteration stops when the relative change in the factor falls below `sensitivity.passthrough_tol`, and it raises after `passthrough_max_iter` iterations.
8. **Carry-over from the first plan's review** (your call, "fold into the next plan"): Task 1 does the fetch hardening; Task 2 adds the BEA API with `NoteRef` parsing; Task 4 adds `WKHP`/`WKWN` > 0 to the wage check. The like-for-like wage check (COW 7 added) is already done.

## Review Focus

1. **Subset rescaling misses the replicate weights**, so 2022–24 MOEs are wrong by a factor. Test in Task 5: `test_year_subset_scales_replicates`.
2. **Suppressed compensation turns into a "pass"** (GOS computed as if comp were 0). Test in Task 8: `test_suppressed_comp_gives_unknown_not_pass`.
3. **The government line reads as "fails self-funding"**, an accounting artifact (SPEC §6). Test in Task 8: `test_government_self_funding_is_na`.
4. **An out-of-state commuter's household is typed from a partial household**, because members come from the wrong source file. Test in Task 6: `test_commuter_household_typed_from_parquet`.
5. **BEA and PUMS dollars in different years**, so ratios are off by 3–23%. Test in Task 8: `test_bea_converted_to_target_dollars`.

---

## Findings from reconnaissance (2026-09-27, live)

- **BEA line codes.** CAGDP2 and SAGDP2/3/4/7 share line codes 1–92, and the 20 lines in Decision 5 partition line 1. CAINC6N uses its own codes. The map is: 3 → 81 + 100; 6 → 200; 10 → 300; 11 → 400; 12 → 500; 34 → 600; 35 → 700; 36 → 800; 45 → 900; 51 → 1000; 56 → 1100; 60 → 1200; 64 → 1300; 65 → 1400; 69 → 1500; 70 → 1600; 76 → 1700; 79 → 1800; 82 → 1900; 83 → 2000. CAINC6N total = 1, private = 81 + 90. In 2024, Orleans CAINC6N lines 100 (forestry and fishing) and 200 (mining) are `(D)`.
- **GOS identity.** For Louisiana, SAGDP2 − SAGDP4 − SAGDP3 − SAGDP7 is within $0.05M on all 20 lines and line 1, for every year 2020–24 (SAGDP2 is rounded to millions). There are no flagged cells in SAGDP2/3/4/7 or CAGDP2 on these lines for 2020–24.
- **National GDP.** `SAGDP.zip` contains `SAGDP2_US_1997_2025.csv` (geo `00000`).
- **BEA API.** It works with GET and the `BEA_API_KEY` env var. `FixedAssets` / `FAAt304ESI` has 96 lines in millions (`UNIT_MULT` 6), and values carry thousands separators ("3,992,907"). The line map to our industries is: 3 → 2, 6 → 5, 10 → 9, 11 → 13, 12 → 14, 34 → 40, 35 → 43, 36 → 48, 45 → 57, 51 → 62, 56 → 73, 60 → 76, 64 → 80, 65 → 81, 69 → 84, 70 → 85, 76 → 90, 79 → 93, 82 → 96.
- **Personal income and PCE.** SAPCE1 line 1 = total PCE (LA). CAINC1 line 1 and SAINC1 line 1 = personal income.
- **NAICSP.** The universe has 455 (COW, NAICSP) pairs, no nulls, and no private COW with NAICSP `92*`. The two-character prefixes are 11, 21, 22, 23, 31–33, `3M`, 42, 44, 45, 48, 49, `4M`, 51–56, 61, 62, 71, 72, 81, 92. `3MS`, `4MS`, `42S` and `22S` are "not specified" codes within their sector.
- **PUMS household codes.** `RELSHIPP`: 20 reference, 21–24 spouse or partner, 25–27 own, adopted or step child, 28–36 other relatives and nonrelatives, 37–38 group quarters. `SFN` 1–4 is the subfamily number. `SFR`: 1–2 couple, 3 parent, 4–6 child. `SERIALNO` containing `GQ` marks group quarters.
- **Official POWPUMA composition** (IPUMS, unblocked 2026-09-27): `https://usa.ipums.org/usa/resources/volii/county_migpuma_pwpuma_2022.xls` (columns: residence state, county, place-of-work state, POWPUMA; header row 1) and `.../puma_migpuma1_pwpuma00_2020.xls` (state, PUMA, place-of-work state, POWPUMA). They are legacy `.xls` files. Checked by hand: county 071 → only `02400`; `02400` → only county 071 and PUMAs 02401–02403; `02390` = counties 051, 075, 087. This confirms the checkpoint.

## File Structure

```
config.yaml                          # + residence_pumas, cow_class, crosswalk rules, capacity, sensitivity keys
src/nola_lw/fetch/common.py          # Task 1: .part cleanup, redacted errors
src/nola_lw/cli.py                   # Task 1: continue past a failed source; Task 10: pipeline
src/nola_lw/fetch/bea_api.py         # Task 2: throttled GET, NoteRef-aware parse, FAAt304ESI
src/nola_lw/fetch/ipums.py           # Task 3: IPUMS POWPUMA composition
src/nola_lw/build/universe.py        # Task 4: load_persons, build_universe, self_employed_count
src/nola_lw/analysis/se.py           # Task 5: replicate_estimate, year_subset
src/nola_lw/analysis/gaps.py         # Tasks 5–6: floor gap, breakdowns, leakage, household table
src/nola_lw/build/households.py      # Task 6: family_units
src/nola_lw/build/crosswalk.py       # Task 7: draft_crosswalk, apply_crosswalk
crosswalks/cow_naicsp_to_bea.csv     # Task 7: cow,naicsp,bea_line (hand-checked)
crosswalks/bea_industries.csv        # Task 7: line,label,cainc6n_lines,fa_line
src/nola_lw/analysis/capacity.py     # Task 8
src/nola_lw/analysis/sensitivity.py  # Task 9
src/nola_lw/report/results.py        # Task 10: results.md, CSVs, qa.md
src/nola_lw/report/charts.py         # Task 10: two PNGs
src/nola_lw/pipeline.py              # Task 10: run(cfg)
```

---

### Task 1: Fetch hardening (review carry-over)

**Files:** Modify `src/nola_lw/fetch/common.py` and `src/nola_lw/cli.py`. Test in `tests/test_common.py` and `tests/test_cli.py`.

- [ ] **Step 1: Write the failing tests:**
  - `test_failed_download_leaves_no_part_file`: a transport returning 500 → `httpx.HTTPStatusError` raised, and no `*.part` file in `tmp_path`.
  - `test_error_message_redacts_key`: a 500 with `params={"UserID": "SECRET"}` → `"SECRET" not in str(excinfo.value)`.
  - `test_fetch_continues_past_failed_source` (monkeypatch the source functions): bls raises and bea succeeds → bea ran, and `SystemExit` at the end names `bls`.
- [ ] **Step 2:** Run the tests; they fail.
- [ ] **Step 3:** In `download`, unlink the `.part` file in `finally` when present. Catch `httpx.HTTPStatusError` and re-raise `RuntimeError(f"GET {redact(url)} -> {status}")` from None. In `cli.fetch`, collect failures and raise `SystemExit` listing them after all sources have run.
- [ ] **Step 4:** Run `uv run pytest -q`; it passes.
- [ ] **Step 5:** Commit: `fetch: clean partial files, redact errors, continue past a failed source`.

### Task 2: BEA API client and national CFC shares

**Files:** Create `src/nola_lw/fetch/bea_api.py` and `tests/test_bea_api.py`, with the fixture `tests/fixtures/bea_api_fa.json` (trimmed real `FAAt304ESI` response: lines 1, 2, 5, 93 and one fabricated `NoteRef` "(D)" cell, marked as fabricated in the test). Modify `config.yaml` and `cli.py`.

**Interfaces:**
- Produces: `parse_api(data: list[dict], unit_mult_key="UNIT_MULT") -> pl.DataFrame` with columns `table, line_code, line_desc, year:int, value:float|null, flag:str|null`. Values are scaled by 10**UNIT_MULT and thousands separators stripped. A `NoteRef` containing a suppression flag gives null value plus that flag, **even when `DataValue` is "0"**.
- `fetch_fixed_assets(cfg) -> Path` makes one GET per call (`Year` = comma-joined pool years) to `bea.api_base`, with `UserID` from env, through `download()` (manifest, redacted). Any `Error` key anywhere in the response raises. Requests are spaced by `bea.api_min_interval_s`.
- `load_fixed_assets(cfg) -> pl.DataFrame` parses the saved JSON.
- Config: `bea.api_base: "https://apps.bea.gov/api/data"`, `bea.api_min_interval_s: 1`, `bea.fixed_assets: {dataset: FixedAssets, table: FAAt304ESI}`, `bea.national_geo: "00000"`, `bea.national_abbr: "US"`.
- Modify `fetch.bea.load_bea` so it also returns SAGDP2 for `national_geo` from the `_US_` file.

- [ ] **Step 1: Write the failing tests:**
  - `test_api_suppressed_zero_is_null`: `{"DataValue": "0", "NoteRef": "(D)"}` → value None, flag "(D)".
  - `test_api_literal_zero_stays_zero`: `DataValue` "0" with no suppression note → 0.0, flag None.
  - `test_api_units_and_commas`: "3,992,907" with `UNIT_MULT` "6" → 3_992_907e6.
  - `test_api_error_is_fatal`: `{"BEAAPI": {"Error": {...}}}` → `RuntimeError`.
  - Parametrize the existing `test_parse_suppressed` (in `test_bea.py`) over `(D)`, `(NA)`, `(NM)` and `(L)`.
- [ ] **Step 2:** Run the tests; they fail.
- [ ] **Step 3:** Implement. Wire `fetch --only bea` to also call `fetch_fixed_assets`.
- [ ] **Step 4:** Run the tests; they pass. Run `uv run nola-lw fetch --only bea` live. One manifest row has the key `REDACTED`, and `load_fixed_assets` has 96 lines × 5 years.
- [ ] **Step 5:** Commit: `fetch: BEA API client (NoteRef-aware) and FAAt304ESI depreciation`.

### Task 3: Official POWPUMA composition check

**Files:** Create `src/nola_lw/fetch/ipums.py` and `tests/test_ipums.py`, with the fixture `tests/fixtures/ipums_county_pwpuma.csv` (the LA rows of the real file plus two MS rows, saved as CSV). Modify `checkpoint.py` §1, `crosswalks/powpuma_orleans.csv`, `config.yaml` (`pums.powpuma_composition_url`, the county file URL in the Findings) and `pyproject.toml` (+ `fastexcel`, so `pl.read_excel` can read `.xls`).

**Interfaces:**
- `fetch_composition(cfg) -> Path` downloads through `download()`.
- `read_composition(path) -> pl.DataFrame` has the columns `st, county, pwst, powpuma`, all strings.
- `orleans_powpumas(comp, cfg) -> dict` returns `{"powpumas": [...] for st/county = Orleans, "counties": [...] in those powpumas}`.

- [ ] **Step 1:** Write the failing test `test_orleans_powpuma_from_composition`: the fixture gives `{"powpumas": ["02400"], "counties": ["071"]}`.
- [ ] **Step 2:** Run it; it fails. **Step 3:** Implement. Add a fourth check to checkpoint §1 ("official composition: 02400 ↔ county 071 only") and make the verdict require it. Replace the "not checked" caveat with the file's URL. Add the file to `crosswalks/powpuma_orleans.csv` `source`. **Step 4:** Tests pass. Run `nola-lw checkpoint`: §1 reads CONFIRMED with the official check. If it doesn't, **STOP and report.**
- [ ] **Step 5:** Commit: `checkpoint: verify Orleans POWPUMA against the IPUMS composition file`.

### Task 4: Worker universe and hourly wages (SPEC §11.3)

**Files:** Create `src/nola_lw/build/__init__.py`, `src/nola_lw/build/universe.py` and `tests/test_universe.py`. Modify `checkpoint.py` (use `load_persons`; add `WKHP`/`WKWN` > 0 to `wage_check`) and `config.yaml`.

**Interfaces:**
- Config: `orleans.residence_pumas: ["02401", "02402", "02403"]`; `universe.cow_class: {"1": private, "2": nonprofit, "3": public, "4": public, "5": public}`.
- `load_persons(cfg, raw=Path("data/raw")) -> pl.DataFrame` loads **all** persons from the LA and MS files (from `pums.bulk_state_fips`) plus `other_states.parquet`, with the column `src` ∈ {"la", "ms", "other"}. It raises `FileNotFoundError` naming what is missing, including other states not in `.done`. Move `checkpoint._load_persons` onto it; the checkpoint filters `POWSP` itself.
- `build_universe(persons, cpi_json, cfg) -> pl.DataFrame` returns one row per worker with `POWSP` = powsp, `POWPUMA` ∈ powpuma, `COW` ∈ cow_wage, and `WAGP`, `WKHP`, `WKWN` all > 0. Added columns:
  - `year` (SERIALNO[:4])
  - `cow_class`
  - `residence` ∈ {orleans, other_la, out_of_state}, where orleans = `STATE` = state_fips and `PUMA` ∈ residence_pumas
  - `earnings` = WAGP·ADJINC/1e6·cpi_factor
  - `hours` = WKHP·WKWN
  - `wage_hr` = earnings/hours
  - `outlier` = wage_hr < wage_min or > wage_max

  It keeps every person column, including `SERIALNO`, `SPORDER`, `src` and the replicate weights.
- `self_employed_count(persons, cfg) -> tuple[float, float]` gives the weighted count and SE of place-of-work-Orleans persons with `COW` ∈ cow_self + cow_unpaid.

- [ ] **Step 1: Write the failing tests** on a synthetic frame (no files):
  - `test_universe_filters`: rows failing each filter (another POWPUMA, COW 6, WKHP 0, WKWN 0, WAGP 0) are all excluded.
  - `test_wage_hr`: WAGP 41,600, ADJINC 1,050,000, WKHP 40, WKWN 52, factor 1.0278 → 41,600·1.05·1.0278/2080.
  - `test_outlier_flag`: $1.50 and $600 are flagged, and $20 is not.
  - `test_residence_tags`: LA residents in 02402 → orleans; LA residents in 01500 → other_la; STATE 28 → out_of_state.
  - `test_load_persons_reports_missing(tmp_path)`: an empty dir → `FileNotFoundError` naming `psam_p22.csv`.
- [ ] **Step 2:** Run them; they fail. **Step 3:** Implement. **Step 4:** The tests pass. Live: the universe has about 9.6k records, and the weighted count, weighted outliers and self-employed count are printed to the ledger.
- [ ] **Step 5:** Commit and push: `build: place-of-work universe and hourly wages` (SPEC §11.3 done).

### Task 5: Replicate estimator and floor gap (SPEC §11.4)

**Files:** Modify `src/nola_lw/analysis/se.py`. Create `src/nola_lw/analysis/gaps.py`. Test in `tests/test_se.py` and `tests/test_gaps.py`.

**Interfaces:**
- `replicate_estimate(df, stat: Callable[[pl.DataFrame, str], float]) -> tuple[float, float]` evaluates `stat(df, w)` for `w` = `PWGTP` and each replicate, then applies `replicate_se`. `weighted_total` becomes a one-line use of it.
- `year_subset(df, years: list[int], pool: list[int]) -> pl.DataFrame` filters `year` and multiplies `PWGTP` and `PWGTP1..80` by (pool span ÷ subset span).
- `add_floor_gap(u, floor: float) -> pl.DataFrame` adds `below` = wage_hr < floor, `gap_hr` = max(0, floor − wage_hr) and `gap_yr` = gap_hr·hours.
- `floor_summary(u) -> dict[str, tuple[float, float]]` with the keys `workers`, `below`, `share_below`, `total_gap`, `mean_short_hr` (weighted mean of gap_hr among below) and `mean_short_yr`.
- `summary_by(u, col: str) -> pl.DataFrame` gives one row per group with `<key>` and `<key>_se` for each summary key.
- `leakage(u) -> pl.DataFrame` gives, by residence, the share of below-floor workers and the share of gap dollars, each with SE.
- Callers drop `outlier` rows unless the sensitivity asks otherwise. The floor is `mit[floor_type]` from the latest county snapshot.

- [ ] **Step 1: Write the failing tests:**
  - `test_year_subset_scales_replicates`: 5 years of rows with weights 1 → the 2022–24 subset has `PWGTP` and `PWGTP80` equal to 5/3.
  - `test_ratio_se`: `replicate_estimate` of a mean on a frame where the replicates shift the mean by ±1 alternately → SE 1.0.
  - `test_gap_math`: floor 20. A worker at $15 × 2,000 h → gap_yr 10,000, below True. A worker at $25 → 0, False. A worker at exactly $20 → below False.
  - `test_floor_summary_hand_computed`: two workers with weights 3 and 1 → share_below 0.75, and total_gap as computed by hand.
  - `test_leakage_shares_sum_to_one`.
- [ ] **Step 2:** Run them; they fail. **Step 3:** Implement. **Step 4:** They pass. Live: log the headline counts in the ledger.
- [ ] **Step 5:** Commit and push: `analysis: floor gap with replicate-weight SEs` (SPEC §11.4 done).

### Task 6: Household typing and the 12-cell table (SPEC §11.5)

**Files:** Create `src/nola_lw/build/households.py` and `tests/test_households.py`. Modify `analysis/gaps.py` and `tests/test_gaps.py`.

**Interfaces:**
- `family_units(persons: pl.DataFrame, cfg) -> pl.DataFrame` has one row per person with `SERIALNO, SPORDER, unit_id, adults (1|2), children, children_over_cap (bool), working (1|2), household` (e.g. `"a2_w2_c1"`, children capped at `households.max_children` = 3). Rules, applied in order within each `SERIALNO`:
  1. `GQ` serials: every person is `a1_w1_c0`.
  2. Subfamily members (`SFN` non-null) form the unit (`SERIALNO`, `SFN`): SFR 1–2 → 2 adults; SFR 3 → 1 adult; SFR 4–6 → children.
  3. The reference family is RELSHIPP 20, plus a spouse or partner (21–24) and own children (25–27) under 18, all not in a subfamily.
  4. Children under 18 who are in neither of those join the reference family (Decision 1).
  5. Everyone else is a single-adult unit.
  6. `working` = 2 if the unit has 2 adults and both have `WAGP` > 0 or `SEMP` ≠ 0, else 1.
- `household_table(u_typed, thresholds: dict[str, float], hours_full_time: int) -> pl.DataFrame` has 12 rows in `HOUSEHOLD_KEYS` order, with `workers`, `share_below_own`, `gap_own`, `share_below_floor`, `annual_share_below` (earnings < threshold·hours_full_time) and `annual_gap`, each with `_se`.

- [ ] **Step 1: Write the failing tests** on synthetic households:
  - `test_couple_both_working_two_kids` → `a2_w2_c2`.
  - `test_subfamily_split`: grandparent reference person plus daughter (SFN 1, SFR 3) plus grandson (SFN 1, SFR 5) → daughter `a1_w1_c1`, grandparent `a1_w1_c0`.
  - `test_roommate_single`, `test_gq_single`, `test_adult_child_single` (age 19).
  - `test_four_kids_capped`: 4 own children → `c3` and `children_over_cap`.
  - `test_spouse_self_employed_counts_as_working` (SEMP −500).
  - `test_unattached_child_joins_reference_family` (grandchild, no subfamily).
  - `test_commuter_household_typed_from_parquet`: a household whose worker has `src` "other" is typed with all its members from that source.
  - `test_household_table_has_12_rows_in_order`.
- [ ] **Step 2:** Run them; they fail. **Step 3:** Implement. **Step 4:** They pass. Live: log the count of universe workers per household cell and the count with `children_over_cap`.
- [ ] **Step 5:** Commit and push: `build: MIT family units and 12-cell table` (SPEC §11.5 done).

### Task 7: Industry crosswalk

**Files:** Create `src/nola_lw/build/crosswalk.py`, `crosswalks/cow_naicsp_to_bea.csv`, `crosswalks/bea_industries.csv` and `tests/test_crosswalk.py`. Modify `config.yaml`.

**Interfaces:**
- Config: `crosswalk.gov_line: "83"` and `crosswalk.prefix_to_line`: {"11": "3", "21": "6", "22": "10", "23": "11", "31": "12", "32": "12", "33": "12", "3M": "12", "42": "34", "44": "35", "45": "35", "4M": "35", "48": "36", "49": "36", "51": "45", "52": "51", "53": "56", "54": "60", "55": "64", "56": "65", "61": "69", "62": "70", "71": "76", "72": "79", "81": "82"}.
- `crosswalks/bea_industries.csv` has the columns `line,label,cainc6n_lines,fa_line`, with the 20 rows from the Findings (`cainc6n_lines` space-separated, `fa_line` empty for 83).
- `draft_crosswalk(pairs: pl.DataFrame, cfg) -> pl.DataFrame` sends `COW` ∈ cow_public → gov_line and the rest by the 2-char `NAICSP` prefix. It raises on an unmapped prefix and on a private `92*`.
- `apply_crosswalk(u, xw: pl.DataFrame) -> pl.DataFrame` adds `bea_line`. It raises `ValueError` listing every (COW, NAICSP) pair in `u` that is missing from `xw`, or duplicated in it.

- [ ] **Step 1: Write the failing tests:**
  - `test_public_cow_maps_to_government`: COW 4, NAICSP 6111 → 83.
  - `test_nonprofit_stays_in_industry`: COW 2, NAICSP 622M → 70.
  - `test_not_specified_codes`: `3MS` → 12 and `4MS` → 35.
  - `test_unmapped_pair_raises` and `test_duplicate_pair_raises`.
  - `test_committed_crosswalk_covers_universe`: loads the real committed CSV and the live universe; skipped when the PUMS data is absent.
  - `test_industries_partition_total`: the 20 lines' CAGDP2 values sum to line 1 within ±$5k for every pool year (live BEA; skip if absent).
- [ ] **Step 2:** Run them; they fail. **Step 3:** Implement. Write the CSV once with `draft_crosswalk` over the live universe pairs, **hand-check it** (read all rows; record in the ledger any rows you changed and why), then commit it. **Step 4:** The tests pass.
- [ ] **Step 5:** Commit: `crosswalk: (COW, NAICSP) → BEA line, hand-checked`.

### Task 8: GOS model and capacity ratios (SPEC §11.6)

**Files:** Create `src/nola_lw/analysis/capacity.py` and `tests/test_capacity.py`. Modify `config.yaml`.

**Interfaces:**
- Config: `capacity: {gos_validation_tol_usd: 500000, total_line: "1", private_line: "2", cainc6n_total: ["1"], cainc6n_private: ["81", "90"]}`.
- `validate_gos_method(bea, cfg) -> float` returns the max |SAGDP2 − SAGDP4 − SAGDP3 − SAGDP7| over the 20 lines, line 1 and the pool years. It raises if that exceeds the tolerance.
- `bea_panel(bea, fa, industries, cfg) -> pl.DataFrame` has rows (line ∈ 20 lines + "total" + "private", year) and columns:
  - `gdp`
  - `comp` (sum of the CAINC6N lines; null if any flagged)
  - `tax_ratio` (SAGDP3/SAGDP2, Louisiana)
  - `gos` = gdp − comp − gdp·tax_ratio
  - `cfc_share` (FA line ÷ US SAGDP2 line)
  - `gos_low` = gos − gdp·cfc_share, where line 83 → 0, "total" = gos − Σ lines' gdp·cfc_share − government GOS, and "private" = gos − Σ private lines' gdp·cfc_share
- `to_target_dollars(panel, cpi_json, cfg) -> pl.DataFrame` scales every money column per year.
- `window_mean(panel, years: list[int]) -> pl.DataFrame` averages by line and is null if any year is null.
- `capacity_table(gap_by_line: pl.DataFrame, panel_mean: pl.DataFrame) -> pl.DataFrame` has one row per line with `gap, gap_se, gdp, comp, gos, gos_low, gap_gdp, gap_comp, gap_gos, gap_gos_low` (the SE of each ratio is gap_se/denominator), plus `self_funding` ∈ {"pass", "fail", "suppressed", "n/a"} ("n/a" for line 83).
- `gos_tests(u, panel_mean) -> dict` holds (a) the private and nonprofit gap (cow_class ∈ private, nonprofit) ÷ private GOS, upper and lower, and (b) the all-sector gap ÷ total GOS, upper and lower. It also holds the government gap ÷ line 83 compensation, each as (est, se).

- [ ] **Step 1: Write the failing tests:**
  - `test_gos_identity`: GDP 100, comp 60, state tax ratio 0.1 → GOS 30.
  - `test_suppressed_comp_gives_unknown_not_pass`: comp flagged → gos null and self_funding "suppressed".
  - `test_government_self_funding_is_na`.
  - `test_bea_converted_to_target_dollars`: values 100 in 2020 and 2024 with CPI annual means 80 and 100 and target 110 → 137.5 and 110.
  - `test_window_mean_null_if_any_year_null`.
  - `test_validate_gos_method_raises_beyond_tol`.
- [ ] **Step 2:** Run them; they fail. **Step 3:** Implement. **Step 4:** They pass. Live: `validate_gos_method` is ≤ $0.05M (per the Findings). Log to the ledger the pool capacity table and every industry that fails self-funding.
- [ ] **Step 5:** Commit and push: `analysis: modeled GOS and capacity ratios` (SPEC §11.6 done).

### Task 9: Sensitivities (SPEC §7)

**Files:** Create `src/nola_lw/analysis/sensitivity.py` and `tests/test_sensitivity.py`. Modify `config.yaml`.

**Interfaces:**
- Config: `sensitivity: {passthrough_tol: 1.0e-6, passthrough_max_iter: 100}`. The p values come from `decisions.passthrough_p`.
- `passthrough_factor(gap_at: Callable[[float], float], base: float, p: float, tol: float, max_iter: int) -> float` returns f satisfying f = 1 + p·gap_at(f)/base, where `gap_at(f)` is the total gap with every threshold × f. It raises `RuntimeError` if the iteration doesn't converge.
- `spending_bases(bea, cpi_json, cfg, years) -> dict[str, float]`:
  - `resident_pce` = SAPCE1 L1 × CAINC1 L1 ÷ SAINC1 L1 (LA/Orleans)
  - `gdp` = CAGDP2 L1

  Both are in target dollars, averaged over `years`.
- `run_sensitivities(u_typed, bea_ctx, cfg) -> pl.DataFrame` has the columns `sensitivity, variant, workers_below, workers_below_se, total_gap, total_gap_se, factor` and one row for each of:
  - the headline
  - the 3 p × 2 bases
  - outliers included
  - the hours rule (annual: gap = max(0, floor·hours_full_time − earnings))
  - Louisiana residents only
  - 2022–24 only
  - metro thresholds (latest `metros_35380` snapshot)

- [ ] **Step 1: Write the failing tests:**
  - `test_passthrough_zero_p_is_one`.
  - `test_passthrough_fixed_point`: gap_at(f) = 10·f, base 100, p 0.5 → f = 1/(1 − 0.05).
  - `test_passthrough_diverges_raises`: gap_at(f) = 1000·f, base 10, p 1.
  - `test_hours_rule_annual_gap`: a part-timer at $25/h with 1,000 h earning $25k and floor $20 → annual gap 20·2,080 − 25,000 = 16,600.
  - `test_sensitivity_rows_complete`: 12 rows with the names above.
- [ ] **Step 2:** Run them; they fail. **Step 3:** Implement. **Step 4:** They pass.
- [ ] **Step 5:** Commit: `analysis: SPEC §7 sensitivities`.

### Task 10: Report, CSVs, charts, pipeline (SPEC §10)

**Files:** Create `src/nola_lw/report/{__init__,results,charts}.py`, `src/nola_lw/pipeline.py` and `tests/test_report.py`. Modify `cli.py`, `pyproject.toml` (+ matplotlib) and `README.md`.

**Interfaces:**
- `pipeline.run(cfg) -> Path` runs: load → universe → floor gap → households → crosswalk → capacity → sensitivities → `write_results`.
- `write_results(ctx: dict, out=Path("data/out")) -> Path` writes `results.md`, one CSV per table (`floor_summary.csv`, `by_industry.csv`, `by_cow_class.csv`, `leakage.csv`, `households.csv`, `capacity.csv`, `gos_tests.csv`, `sensitivities.csv`), and `qa.md`. The qa file covers:
  - MS vs other-state residents' counts, weighted wages and gap
  - outlier drops
  - the self-employed count
  - crosswalk coverage
  - GOS validation
  - industry-years with suppressed compensation
  - `children_over_cap`
- `charts.gap_vs_gos(capacity) -> Path` and `charts.wage_distribution(u, floor) -> Path` write PNGs to `data/out/`.
- Every main table shows 2020–24 with a 2022–24 column, as est ± MOE.
- The headline paragraph must state, from the numbers:
  - workers below the floor and the total gap
  - gap ÷ GDP, compensation and GOS (both GOS tests, with equal prominence)
  - **every industry that fails self-funding, by name**
  - whether 2020–24 and 2022–24 differ beyond their MOEs
  - one sentence on the survey-vs-BEA wage shortfall (−10.3%; −3.9% like-for-like) and that it could overstate the gap (your decision)
- CLI: `nola-lw run` runs `pipeline.run`; `nola-lw all` runs fetch → checkpoint → run.

- [ ] **Step 1: Write the failing tests** with a small synthetic `ctx`:
  - `test_results_has_all_sections`: the headings for the seven tables in SPEC §10 are present.
  - `test_headline_names_failing_industries`: a ctx where line 79 fails → "Accommodation and food services" appears in the headline paragraph.
  - `test_headline_flags_window_difference`: pool and subset differ beyond MOE → the headline says so.
  - `test_csvs_written`: all 8 CSVs exist.
  - `test_charts_written`: both PNGs exist and are non-empty.
- [ ] **Step 2:** Run them; they fail. **Step 3:** Implement (read the `dataviz` skill before the charts). **Step 4:** They pass. Run `uv run nola-lw run` live, then read `results.md` and `qa.md` in full. Any number that looks implausible gets debugged (superpowers:systematic-debugging), not reworded.
- [ ] **Step 5:** Commit `results.md`, the CSVs, the PNGs and `qa.md`, and push: `report: results, tables and charts` (SPEC §11.7 done). **STOP and report the headline to the user.**
