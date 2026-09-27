# Scaffold, Fetch, Checkpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build SPEC §11 steps 1–2. Scaffold the repo, fetch every source with a manifest, and produce the hard-checkpoint report. Then **stop** for the user's confirmation.

**Architecture:** This is a plain Python package, `nola_lw`, with one fetch module per source. Each fetch module writes to `data/raw/` and appends to `data/raw/manifest.csv`. A `checkpoint` module reads the raw files and writes `data/out/checkpoint.md`. A single `nola-lw` CLI runs everything. All constants live in `config.yaml`. There is no orchestration framework.

**Tech Stack:** Python ≥3.12 (installed by uv), uv, polars, duckdb (for later steps; not needed here), httpx, pyyaml, pytest.

**Spec:** `SPEC.md` v0.2 (approved 2026-09-26).

## Global Constraints

- Place of work only; never mix residence- and workplace-based measures (SPEC §2). The only residence-based inputs are CAINC1/SAINC1, used as the SAPCE allocator (§7.1).
- No numbers in code: every constant comes from `config.yaml` or fetched data (§9).
- Every raw download is recorded in `data/raw/manifest.csv` with URL, fetch date and sha256 (§9). API keys are never written to the manifest, logs or snapshots.
- `data/raw/` and `data/out/` are gitignored, except `results.md`, `qa.md`, `*.csv` and `*.png`. `data/snapshots/` and `crosswalks/` are committed.
- MIT thresholds are scraped, never hardcoded. The committed dated snapshot is reused unless `--refresh-mit` is passed (§9).
- PUMS codes (`POWSP`, `POWPUMA`, `PUMA`, `NAICSP`, `COW`, `SERIALNO`) are read as strings. Leading zeros matter (for example `POWSP` = `022`).
- **Keys.** No Census key is used, since all PUMS data comes from the bulk files. BLS works keyless, with `BLS_API_KEY` optional. **BEA data comes from BEA's bulk regional ZIPs** (plain GET, no key and no rate limit). `BEA_API_KEY` is read from an environment variable and is needed only for later API calls, such as the NIPA fixed-asset tables in §11.6. The environment must list `apps.bea.gov` under allowed domains. These keys are usage identifiers, not secrets, but they are still kept out of files.
- Commit after each task and push after each completed SPEC §11 step.

## Review Focus

1. **BEA suppression flags.** `(D)`, `(NA)`, `(NM)` and `(L)` must parse as null with the flag kept, never as 0. In the API (the fallback path), a suppressed cell arrives as `DataValue` "0" plus `NoteRef` "(D)". Covered by a test in Task 5.
2. **API keys written to disk.** URL keys (`key`, `UserID`, `registrationkey`) are removed in the manifest. Covered by a test in Task 2.
3. **MIT page layout changes.** The scraper must fail loudly if it doesn't find exactly 12 "Living Wage" values under the expected household headers, rather than assigning columns silently. Covered by a test in Task 3.
4. **Missing CPI target month.** If December 2025 isn't in the BLS series, raise an error; never fall back silently to another month. Covered by a test in Task 4.
5. **Leading-zero codes.** `POWSP` and `POWPUMA` read as integers would drop leading zeros and match nothing. Covered by a test in Task 6.

---

## Findings from reconnaissance (2026-09-26, read-only)

- The bulk PUMS files download without a key: `https://www2.census.gov/programs-surveys/acs/data/pums/2024/5-Year/csv_{p,h}{la,ms}.zip` (for example `csv_pla.zip`, 29.8 MB).
- The 2020–2024 data dictionary (`PUMS_Data_Dictionary_2020-2024.csv`) has **one** `POWPUMA` field ("based on 2020 Census definitions") and one `NAICSP` field ("based on 2022 NAICS"). There is no 2010-vintage PUMA field.
- In `psam_p22.csv` with `POWSP == "022"`, POWPUMA `02400` carries 213,363 weighted workers. The tract-to-PUMA file puts residence PUMAs 02401–02403 wholly in parish 071 (Orleans). Candidate: Orleans = POWPUMA `02400`. The checkpoint confirms this.
- Survey-year record counts in the LA person file: 2020: 31,513; 2021: 43,663; 2022–24: about 45k each.
- **BEA, checked live on 2026-09-27:** the table names above exist. CAINC5N line 50 and CAINC6N line 5 are identical (2020: 11,644,740; 2024: 14,206,017, in thousands). Orleans CAGDP2 has no zero or suppressed cells for 2019–2024. CAINC6N has 133 zero cells for 2020–24, mostly at the subsector level. Data were last updated 2026-02-05.
- The BLS v1 API works without a key: `CUUR0300SA0` returns monthly data through 2026-08.
- **BEA access (2026-09-27).** A proxy-held API credential only works with POST, and it breaks every GET to `apps.bea.gov`, including the bulk ZIPs. For the implementation session, the credential is replaced by a `BEA_API_KEY` environment variable, and `apps.bea.gov` is added to allowed domains. The ZIP layout wasn't observable from this session, so **Task 5, Step 0 verifies it first.** The Census API is GET-only, hence the PUMS bulk files.

## File Structure

```
pyproject.toml                    # package + `nola-lw` script entry
config.yaml                       # all constants (Task 1)
.env.example                      # BEA_API_KEY, BLS_API_KEY (both optional locally), empty values
src/nola_lw/__init__.py
src/nola_lw/config.py             # load_config()
src/nola_lw/cli.py                # argparse: fetch | checkpoint | all
src/nola_lw/fetch/common.py       # download(), manifest, key redaction
src/nola_lw/fetch/mit.py          # scrape + parse thresholds and price basis
src/nola_lw/fetch/bls.py          # CPI series + cpi_factor()
src/nola_lw/fetch/pums.py         # bulk LA/MS files + filtered other-state person files
src/nola_lw/fetch/bea.py          # Regional tables, parse with suppression flags
src/nola_lw/analysis/se.py        # replicate-weight SE / 90% MOE
src/nola_lw/checkpoint.py         # checkpoint report
crosswalks/powpuma_orleans.csv    # vintage,powsp,powpuma,county_fips,source
tests/fixtures/                   # saved MIT HTML, small BEA/BLS JSON, tiny PUMS CSV
tests/test_*.py
```

---

### Task 1: Scaffold, config, CLI skeleton

**Files:** Create `pyproject.toml`, `config.yaml`, `.env.example`, `src/nola_lw/{__init__,config,cli}.py` and `tests/test_config.py`. Modify `README.md`.

**Interfaces:**
- Produces: `load_config(path: Path = Path("config.yaml")) -> dict` and the CLI `nola-lw {fetch [--refresh-mit] [--only SOURCE], checkpoint, all}`.

- [ ] **Step 1:** Run `uv python install 3.12` and `uv init --package`, or hand-write `pyproject.toml` with `requires-python = ">=3.12"`, the dependencies `httpx`, `polars`, `duckdb` and `pyyaml`, dev dependency `pytest`, and `[project.scripts] nola-lw = "nola_lw.cli:main"`. Run `uv sync`. It succeeds, and `uv run python -V` reports 3.12.x.
- [ ] **Step 2: Write `config.yaml`** with these keys and values, copied from SPEC:
  - `years: {pool: [2020, 2024], subset: [2022, 2024]}`
  - `orleans: {state_fips: "22", county_fips: "071", powsp: "022", powpuma: ["02400"]}` (the checkpoint confirms these)
  - `mit: {county_path: "counties/22071", metro_path: "metros/35380", methodology_path: "pages/methodology", base_url: "https://livingwage.mit.edu", floor_type: "a1_w1_c0", hours_full_time: 2080}`
  - `cpi: {series: "CUUR0300SA0", base_year: 2024, target: "2025-12"}`
  - `pums: {bulk_base: "https://www2.census.gov/programs-surveys/acs/data/pums/2024/5-Year", bulk_states: ["la", "ms"], other_states: [the 49 other postal codes (48 states + DC), lower-case], dictionary_url: ".../PUMS_Data_Dictionary_2020-2024.csv"}`
  - `bea: {county_geo: "22071", state_geo: "22000", county_tables: [CAGDP2, CAINC5N, CAINC6N, CAINC1], state_tables: [SAGDP2, SAGDP3, SAGDP4, SAGDP7, SAINC1, SAPCE1], zip_base: "https://apps.bea.gov/regional/zip", zips: [CAGDP2, CAINC5N, CAINC6N, CAINC1, SAGDP, SAINC, SAPCE], wages_line: {table: CAINC5N, line: "50"}, wages_crosscheck: {table: CAINC6N, line: "5"}}`. Table names were confirmed live on 2026-09-27. SAGDP3 is taxes less subsidies, SAGDP7 is GOS (used for validation).
  - `universe: {cow_wage: ["1", "2", "3", "4", "5"], cow_public: ["3", "4", "5"], cow_self: ["6", "7"], cow_unpaid: ["8"], wage_min: 2, wage_max: 500}`
  - `decisions:` one key for each item in SPEC §12 a–f, with a string value (for example `household_unit: family_with_subfamilies`, `thresholds: orleans`, `sensitivity_thresholds: metro`, `gos_test: both`, `out_of_state: all_state_api`, `passthrough_bases: [resident_pce, gdp]`, `passthrough_p: [0, 0.5, 1]`, `headline_years: pool`, `alongside_years: subset`)
  - `checkpoint: {wage_tolerance: 0.15}`, `moe_z: 1.645`
- [ ] **Step 3: Write the failing test** `tests/test_config.py::test_config_has_required_keys`: `cfg = load_config()`; assert `cfg["orleans"]["powsp"] == "022"`, `cfg["cpi"]["target"] == "2025-12"`, `cfg["checkpoint"]["wage_tolerance"] == 0.15`, `len(cfg["pums"]["other_states"]) == 49`, `"la" not in cfg["pums"]["other_states"]`, and that every value in `orleans` is a `str`.
- [ ] **Step 4:** Implement `load_config` with `yaml.safe_load`, and a `main()` stub whose subcommands print "not implemented". Run `uv run pytest -q`; it passes.
- [ ] **Step 5:** Create `.env.example` with `BEA_API_KEY=` and `BLS_API_KEY=` (both optional). Replace the README's Reproduce section with `uv sync`, `cp .env.example .env` and `uv run nola-lw all`.
- [ ] **Step 6:** Commit: `scaffold: package, config, CLI skeleton`.

### Task 2: Download helper and manifest

**Files:** Create `src/nola_lw/fetch/common.py` and `tests/test_common.py`.

**Interfaces:**
- Produces: `download(url: str, dest: Path, *, params: dict | None = None, client: httpx.Client | None = None, force: bool = False) -> Path`. It appends one row to `data/raw/manifest.csv` with the columns `url, fetched_at_utc, sha256, bytes, path`. `redact(url: str) -> str` replaces the values of `key`, `UserID` and `registrationkey` with `REDACTED`. It skips a download when `dest` exists, `force` is false and its sha256 matches the manifest.

- [ ] **Step 1: Write the failing tests** using `httpx.MockTransport`:
  - `test_download_writes_manifest_row`: the sha256 in the manifest equals `hashlib.sha256(body).hexdigest()`, and `bytes` equals `len(body)`.
  - `test_manifest_redacts_keys`: `params={"key": "SECRET", "UserID": "SECRET2"}` puts no `SECRET` substring anywhere in the manifest file.
  - `test_skip_when_unchanged`: a second call with the same dest makes zero requests (the transport counts calls).
- [ ] **Step 2:** Run them; they fail on import.
- [ ] **Step 3:** Implement with `httpx.Client(timeout=300, follow_redirects=True)`, and write through a temporary file then rename.
- [ ] **Step 4:** Run the tests; they pass.
- [ ] **Step 5:** Commit: `fetch: download helper with sha256 manifest and key redaction`.

### Task 3: MIT scraper

**Files:** Create `src/nola_lw/fetch/mit.py`, `tests/test_mit.py`, and the fixtures `tests/fixtures/mit_22071.html` and `mit_methodology.html`, saved from the live pages.

**Interfaces:**
- Produces: `HOUSEHOLD_KEYS: list[str]` = `a1_w1_c0..c3`, `a2_w1_c0..c3`, `a2_w2_c0..c3`, in MIT's page column order.
- `parse_thresholds(html: str) -> dict[str, float]`, returning 12 keys.
- `parse_price_basis(html: str) -> str`, which returns, for example, `"December 2025"` from the phrase "adjusted for inflation to <Month YYYY> dollars".
- `scrape(cfg, snapshot_dir=Path("data/snapshots"), refresh=False) -> Path` writes `mit_{area}_{YYYY-MM-DD}.csv` for the county and the metro, with the columns `area, household, adults, working, children, hourly, price_basis, fetched`, plus the raw HTML. With `refresh=False`, it returns the newest existing snapshot.

- [ ] **Step 1: Write the failing tests:**
  - `test_parse_orleans`: `t["a1_w1_c0"] == 20.29`, `t["a2_w1_c0"] == 28.86` and `t["a2_w2_c3"] == 28.45` (the fixture values match SPEC §3).
  - `test_parse_rejects_layout_change`: HTML with 11 values raises `ValueError`.
  - `test_price_basis`: returns `"December 2025"`.
- [ ] **Step 2:** Run them; they fail.
- [ ] **Step 3:** Implement with the standard library (`re` and `html.parser`) and no new dependency. Find the table row labelled "Living Wage", require exactly 12 `$` values, and check that the header text includes "1 ADULT" and "2 ADULTS" labels, raising otherwise.
- [ ] **Step 4:** Run the tests; they pass. Then run `uv run nola-lw fetch --only mit --refresh-mit` against the live site. Two dated snapshot CSVs appear, and the county one matches the SPEC §3 table.
- [ ] **Step 5:** Commit the code, tests, fixtures and `data/snapshots/`: `fetch: MIT threshold scraper with dated snapshots`.

### Task 4: BLS CPI

**Files:** Create `src/nola_lw/fetch/bls.py` and `tests/test_bls.py`, with the fixture `tests/fixtures/bls_cpi.json`, a trimmed real response.

**Interfaces:**
- Produces: `fetch_cpi(cfg) -> Path`. It uses v2 with `registrationkey` when `BLS_API_KEY` is set, otherwise v1, over the years 2019–2026, and saves JSON to `data/raw/bls/`.
- `cpi_factor(cpi_json: dict, base_year: int, target: str) -> float` returns the target month value divided by `annual_mean(cpi_json, base_year)`. `annual_mean(cpi_json: dict, year: int) -> float` is the mean of the 12 monthly values and raises if any month is missing. Task 7 uses it to put BEA years in 2024 dollars.

- [ ] **Step 1: Write the failing tests:**
  - `test_cpi_factor_synthetic`: base-year months all 100 and the target month 105 gives 1.05.
  - `test_cpi_factor_missing_month`: `ValueError` naming "2025-12" when that month is absent.
  - `test_cpi_factor_incomplete_base_year`: `ValueError` when fewer than 12 base months are present.
- [ ] **Step 2:** Run them; they fail.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests; they pass. Run `uv run nola-lw fetch --only bls`; a manifest row appears.
- [ ] **Step 5:** Commit: `fetch: BLS CPI-U South and Dec-2025/2024 factor`.

### Task 5: BEA regional tables (bulk ZIPs)

**Files:** Create `src/nola_lw/fetch/bea.py` and `tests/test_bea.py`, with the fixture `tests/fixtures/bea_sample.csv`, a trimmed copy of a real file from Step 0.

**Interfaces:**
- Produces: `fetch_zips(cfg) -> list[Path]` downloads `{zip_base}/{name}.zip` for each name in `bea.zips` through `download()` (manifest row, sha256), then extracts to `data/raw/bea/{name}/`.
- `parse_bea_csv(path: Path, geo: str) -> pl.DataFrame`, with the columns `table, line_code, line_desc, geo, year:int, value:float|null, flag:str|null`. It keeps only rows for `geo` and reshapes the year columns from wide to long. `(D)`, `(NA)`, `(NM)` and `(L)` become a null value with the flag kept. The footnote and source lines at the end of the file are dropped. Units are read from the file's unit column and scaled to dollars.
- `load_bea(cfg) -> pl.DataFrame` gives the tables in `bea.county_tables` for `county_geo` and `bea.state_tables` for `state_geo`, over `years.pool`.

- [ ] **Step 0: Verify the ZIP layout live, before writing the tests.** Download `CAINC6N.zip` and `SAGDP.zip`. Record their file names, the header row, how "(D)" appears, the footer lines, and the unit column in the plan's findings section. Then check that Orleans CAINC5N line 50 in the file equals the API figures recorded in the findings (2020: 11,644,740; 2024: 14,206,017, in thousands), and that CAINC5N line 200 for 2024 is "(D)". **If a ZIP is missing or its layout differs from what's assumed here, stop and tell the user.** The fallback is the API with `BEA_API_KEY` from the environment, following the findings above: throttle to 60 per minute, read `NoteRef`, and treat errors as fatal.
- [ ] **Step 1: Write the failing tests** against the Step 0 fixture:
  - `test_parse_suppressed`: a `(D)` cell gives `value is None` and `flag == "(D)"`, never 0.
  - `test_parse_numbers_and_units`: a known Orleans value parses to the expected dollars, using the unit column.
  - `test_footer_dropped`: no rows from the footnote lines.
  - `test_geo_filter`: only rows with `geo == "22071"` remain.
- [ ] **Step 2:** Run them; they fail.
- [ ] **Step 3:** Implement. Read the CSVs with `pl.read_csv(..., infer_schema_length=0)` so every column comes in as text, then cast. The files are latin-1 encoded if Step 0 shows that.
- [ ] **Step 4:** Run the tests; they pass. Run `uv run nola-lw fetch --only bea` live; the manifest has one row per ZIP.
- [ ] **Step 5:** Commit: `fetch: BEA regional bulk ZIPs with suppression flags`.

### Task 6: PUMS fetchers (bulk files, all states)

**Files:** Create `src/nola_lw/fetch/pums.py` and `tests/test_pums.py`, with the fixture `tests/fixtures/pums_tiny.csv`: about 10 rows over 3 households, one of which has a member with `POWSP=022`, `POWPUMA=02400`, and a letter in `NAICSP`.

**Interfaces:**
- Produces: `PERSON_VARS: list[str]` = `SERIALNO, SPORDER, PWGTP, WAGP, ADJINC, WKHP, WKWN, COW, NAICSP, POWSP, POWPUMA, ST, PUMA, AGEP, RELSHIPP, SFN, SFR, SEMP`, plus `REP_VARS` = `PWGTP1..PWGTP80`.
- `read_persons(path: Path) -> pl.DataFrame` reads `PERSON_VARS + REP_VARS`, with every code column as `pl.Utf8`.
- `keep_la_worker_households(df: pl.DataFrame, powsp: str) -> pl.DataFrame` keeps every person whose `SERIALNO` has at least one member with `POWSP == powsp`.
- `fetch_bulk(cfg) -> list[Path]` downloads the LA and MS person and household zips and the data dictionary, then extracts them to `data/raw/pums/`.
- `fetch_other_states(cfg) -> Path`, for each postal code in `pums.other_states` in turn: download `csv_p{st}.zip`, stream-read it, apply `keep_la_worker_households`, append to `data/raw/pums/other_states.parquet`, and delete the zip and CSV. The manifest keeps each zip's row. On a rerun, skip any state already in the parquet.

- [ ] **Step 1: Write the failing tests:**
  - `test_read_keeps_leading_zeros`: `df["POWSP"]` contains `"022"`, and `df["POWPUMA"]` contains `"02400"`.
  - `test_keep_households`: from the fixture, all members of the household with the `022` worker are kept (including a child with null `POWSP`), and the other two households are dropped.
  - `test_other_states_resumes`: with a fake downloader, a second run makes no requests for states already written.
- [ ] **Step 2:** Run them; they fail.
- [ ] **Step 3:** Implement. Use `pl.scan_csv(..., schema_overrides=...)` so a large state file isn't held in memory, and check free disk before each state.
- [ ] **Step 4:** Run the tests; they pass. Run `uv run nola-lw fetch --only pums` live. The LA/MS files, the dictionary and 49 state zips appear in the manifest. `other_states.parquet` exists, and its weighted `POWSP=022` count is logged.
- [ ] **Step 5:** Commit, then push. This completes SPEC §11 step 1.

### Task 7: Replicate-weight SE and checkpoint report

**Files:** Create `src/nola_lw/analysis/se.py`, `src/nola_lw/checkpoint.py`, `crosswalks/powpuma_orleans.csv`, `tests/test_se.py` and `tests/test_checkpoint.py`.

**Interfaces:**
- Produces: `replicate_se(full: float, reps: Sequence[float]) -> float`, which computes `sqrt(4/80 * Σ(rep − full)²)` and requires `len(reps) == 80`. Also `moe90(se: float, z: float) -> float`, which returns `z * se`, with `z` taken from `cfg["moe_z"]`.
- `weighted_total(df, value_col, weight_prefix="PWGTP") -> tuple[float, float]` returns the estimate and its SE, using the full and 80 replicate weights.
- `powpuma_by_year(df) -> pl.DataFrame` gives the weighted count by survey year (`SERIALNO[:4]`) and `POWPUMA` for `POWSP == orleans.powsp`.
- `wage_check(persons, bea_wages_2024usd) -> dict` returns `survey, survey_moe, bea, pct_diff, flag` for the universe `COW` ∈ `cow_wage`, `WAGP > 0` and Orleans POWPUMA. The survey figure is `Σ PWGTP·WAGP·ADJINC/1e6`, which is an average-year figure in 2024 dollars. The BEA figure is the 2020–24 mean of `bea.wages_line` (CAINC5N line 50, which equals CAINC6N line 5; checked live), with each year converted to 2024 dollars by CPI-U South annual averages. `flag = abs(pct_diff) > wage_tolerance`.
- `suppressed_gdp(cagdp2: pl.DataFrame) -> dict` reads suppression from the `flag` column, never from zeros, and gives, per year, the all-industry total, the sum of disclosed top-level sectors, and the residual = total − disclosed (the GDP in "(D)" cells) and its share.
- `write_report(cfg) -> Path` writes `data/out/checkpoint.md` with the four user checkpoint items plus the `NAICSP` codes by survey year. Any item whose inputs are missing prints "BLOCKED: <missing input>" and never a guessed number.

- [ ] **Step 1: Write the failing tests:**
  - `test_se_formula`: with `full=100`, reps of 101 (40 of them) and 99 (40 of them), SE = sqrt(4/80·80·1) = 2.0.
  - `test_se_requires_80`: `ValueError` on 79 reps.
  - `test_weighted_total_adjinc`: two synthetic workers with ADJINC=1.05e6 give the hand-computed total.
  - `test_wage_check_flag`: a survey of 80 against a BEA figure of 100 gives `pct_diff == -0.20` and `flag is True`; a survey of 90 gives `flag is False`.
  - `test_suppressed_residual`: a total of 100, disclosed sectors 30 + 50 and one `(D)` sector give a residual of 20 and a share of 0.20.
  - `test_report_marks_blocked`: with no BEA files present, the report contains "BLOCKED" and "CAINC5N".
- [ ] **Step 2:** Run them; they fail.
- [ ] **Step 3:** Implement. Write `crosswalks/powpuma_orleans.csv` from the confirmed codes, with the columns `vintage,powsp,powpuma,county_fips,source`. Its source is the data-dictionary label plus the tract-to-PUMA file, and every row is hand-checked.
- [ ] **Step 4:** Run the tests; they pass. Run `uv run nola-lw checkpoint` live and read `data/out/checkpoint.md`.
- [ ] **Step 5:** Commit, then push. **STOP. Report the four checkpoint items to the user and wait for confirmation.**

---

## After the checkpoint (outline only; detailed in a follow-up plan)

- **§11.3 Universe and wages:** `build/universe.py` combines the LA, MS and other-state bulk records. It applies the filters, computes `wage_hr`, applies the CPI factor, flags outliers, counts self-employed workers, and tags residence as Orleans, other LA or out of state (`qa.md` gets the MS/other split).
- **§11.4 Floor gap:** `analysis/gaps.py` computes the gap, counts, shares and mean shortfall with MOEs, broken out by industry, class of worker and residence. Tests use synthetic workers, including the gap-math test.
- **§11.5 Households:** `build/households.py` builds family units with subfamilies (SFN/SFR), caps children at 3, counts working adults, and produces the 12-cell table and the annual version.
- **§11.6 Capacity:** `crosswalks/cow_naicsp_to_bea.csv` gets a coverage test that every (COW, NAICSP) pair in the data maps exactly once. Also: GOS upper and lower bounds (NIPA consumption-of-fixed-capital shares, fetched here), both GOS tests, the government payroll percentage, and the 2022–24 column with 5/3 rescaling.
- **§11.7 Sensitivities and report:** the six §7 sensitivities, `results.md`, the CSVs and two charts.
