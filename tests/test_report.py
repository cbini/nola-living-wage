import functools

import polars as pl

from nola_lw.analysis import capacity as cap
from nola_lw.analysis.gaps import (add_floor_gap, floor_summary, household_table, leakage, summary_by,
                                   window_difference, year_subset)
from nola_lw.config import load_config
from nola_lw.fetch.mit import HOUSEHOLD_KEYS
from nola_lw.report import charts
from nola_lw.report.results import headline, results_md, write_results

CFG = load_config()
LABELS = {"3": "Agriculture, forestry, fishing and hunting", "79": "Accommodation and food services",
          "56": "Real estate and rental and leasing", "83": "Government and government enterprises"}
FLOOR = 20.0
THRESHOLDS = {k: FLOOR + i for i, k in enumerate(HOUSEHOLD_KEYS)}


def _universe(early_wage: float, late_wage: float) -> pl.DataFrame:
    """Three workers per year (hospitality private, government public, agriculture private). Replicate
    weights alternate around the full weight, early years against late, so SEs are small but nonzero."""
    rows = []
    for y in range(2020, 2025):
        wage = early_wage if y < 2022 else late_wage
        for line, cls, res in [("79", "private", "orleans"), ("83", "public", "other_la"),
                               ("3", "private", "out_of_state")]:
            rows.append({"year": str(y), "bea_line": line, "cow_class": cls, "residence": res, "src": "la",
                         "household": HOUSEHOLD_KEYS[0], "wage_hr": wage, "hours": 2000.0, "earnings": wage * 2000})
    u = pl.DataFrame(rows)
    early = pl.col("year").cast(pl.Int64) < 2022
    return u.with_columns(PWGTP=pl.lit(10.0), **{f"PWGTP{i}": pl.when(early).then(10.0 + (-1) ** i * 0.1)
                                                  .otherwise(10.0 - (-1) ** i * 0.1) for i in range(1, 81)})


def _panel(gos_79: float) -> pl.DataFrame:
    """Line 3 has suppressed compensation (so null GOS), as in BEA CAINC6N 2024."""
    return pl.DataFrame({
        "line": ["3", "56", "79", "83", "total", "private"],
        "gdp": [1e8, 3e8, 1e9, 1e9, 2e9, 1e9], "comp": [None, 1e7, 5e8, 8e8, 1.3e9, 5e8],
        "tax_ratio": [0.1, 0.1, 0.1, 0.0, 0.05, 0.1], "cfc_share": [0.1, 0.1, 0.1, None, None, None],
        "gos": [None, 1e8, gos_79, 2e8, 6e8, 4e8], "gos_low": [None, 1e8, gos_79, 0.0, 4e8, 3e8],
        "wages": [None, None, None, None, 1e9, None]})


@functools.cache
def _survey_windows(early_wage: float, late_wage: float) -> dict:
    """The survey-side (expensive, replicate-weight) window pieces; the GOS-dependent capacity table
    is rebuilt per call to `_ctx`. gos_tests only reads the total/private/government rows, which
    `gos_79` doesn't touch."""
    u = _universe(early_wage, late_wage)
    windows = {}
    for name in ("pool", "subset"):
        years = CFG["years"][name]
        sub = year_subset(u, years, CFG["years"]["pool"])
        g = add_floor_gap(sub, FLOOR)
        windows[name] = {"years": years, "summary": floor_summary(g), "by_industry": summary_by(g, "bea_line"),
                         "by_cow": summary_by(g, "cow_class"), "leakage": leakage(g),
                         "households": household_table(sub, THRESHOLDS, CFG["mit"]["hours_full_time"],
                                                       HOUSEHOLD_KEYS[0]),
                         "gap_by_line": cap.gap_by_line(g, CFG), "gos_tests": cap.gos_tests(g, _panel(0.0), CFG)}
    pool = CFG["years"]["pool"]
    window_diff = window_difference(add_floor_gap(u, FLOOR), CFG["years"]["subset"], pool, CFG["moe_z"])
    return {"u": u, "windows": windows, "window_diff": window_diff}


@functools.cache
def _ctx(early_wage=15.0, late_wage=15.0, gos_79=4e8) -> dict:
    base = _survey_windows(early_wage, late_wage)
    u = base["u"]
    windows = {name: w | {"capacity": cap.capacity_table(w["gap_by_line"], _panel(gos_79), "83")}
               for name, w in base["windows"].items()}
    s = windows["pool"]["summary"]
    sens = pl.DataFrame([{"sensitivity": n, "variant": n, "workers_below": s["below"][0], "workers_below_se": 1.0,
                          "total_gap": s["total_gap"][0] * k, "total_gap_se": 1.0, "factor": 1.0}
                         for n, k in [("headline", 1.0), ("hours_rule", 2.0), ("years_2022_2024", 1.0)]])
    qa = {"by_src": [], "outliers": (0, (0.0, 0.0)), "self_employed": (0.0, 0.0),
          "crosswalk": {"pairs_in_data": 2, "crosswalk_rows": 2}, "gos_resid": 0.0,
          "suppressed": pl.DataFrame(), "children_over_cap": (0, (0.0, 0.0)), "minors": (3, (30.0, 1.0))}
    return {"cfg": CFG, "floor": FLOOR, "thresholds": THRESHOLDS, "labels": LABELS, "windows": windows,
            "sensitivities": sens, "window_diff": base["window_diff"], "survey_bea": {"pct": -0.1, "pct_like": -0.04},
            "u": add_floor_gap(u, FLOOR), "qa": qa}


def test_results_has_all_sections(tmp_path):
    text = write_results(_ctx(), tmp_path).read_text()
    for h in ["## 1. Workers below the floor", "## 2. Total gap", "## 3. Gap vs. GDP, compensation and GOS",
              "## 4. Industries and the self-funding test", "## 5. Commuter leakage",
              "## 6. Household types", "## 7. Sensitivities"]:
        assert h in text
    assert "| Agriculture, forestry, fishing and hunting |" in text
    assert "suppressed / suppressed" in text


def test_headline_names_failing_industries():
    text, _ = headline(_ctx(gos_79=1.0))
    assert "Accommodation and food services (both bounds)" in text


def test_headline_expected_failure_that_passes():
    text, _ = headline(_ctx())
    assert "Accommodation and food services, which SPEC §6 expected to fail, passes both bounds" in text


def test_gap_vs_gos_axis_covers_failing_bar():
    cap_ = _ctx(gos_79=5e4)["windows"]["pool"]["capacity"]
    top = cap_.filter(pl.col("line") == "79")["gap_gos"][0]
    assert top > 1  # fails with positive GOS
    assert charts.ratio_axis_max(cap_) >= top * 100


def _table_row(text: str, first_cell: str) -> list[str]:
    line = next(ln for ln in text.splitlines() if ln.startswith(f"| {first_cell} |"))
    return [c.strip() for c in line.strip("|").split("|")]


def test_headline_flags_window_difference_paired():
    """Early workers above the floor, late below: the paired test flags workers below and the gap.
    Identical years: nothing differs. The years_2022_2024 sensitivity row follows the same test even
    though its (stubbed) totals equal the headline's."""
    ctx = _ctx(early_wage=25.0, late_wage=15.0)
    differ, _ = headline(ctx)
    same, _ = headline(_ctx())
    assert "workers below the floor (beyond its 90% MOE)" in differ
    assert "so the windows differ on" in differ
    assert "do not differ beyond their MOEs on any of the three" in same
    assert "(beyond its 90% MOE)" not in same
    text = results_md(ctx)
    assert _table_row(text, "years_2022_2024")[-1] == "yes"
    assert _table_row(results_md(_ctx()), "years_2022_2024")[-1] == "no"


def test_real_estate_disclosure():
    text = results_md(_ctx())
    for bound in ("upper", "lower"):
        for test in ("(a)", "(b)"):
            assert _table_row(text, f"{test} excluding Real estate and rental and leasing, {bound} bound")
    head, _ = headline(_ctx())
    assert "Excluding real estate and rental and leasing, whose GOS includes imputed rent" in head
    # line 56 GOS 1e8 of private 4e8 (25%) and total 6e8 (16.7%); lower 1e8 of 3e8 and 4e8
    assert "is 25.0% of private and 16.7% of total modeled GOS at the upper bound (33.3% and 25.0%" in text


def test_government_gos_ratios_are_na():
    row = _table_row(results_md(_ctx()), "Government and government enterprises")
    assert row[5:7] == ["n/a", "n/a"]
    assert row[4] != "n/a"  # gap ÷ compensation is shown


def test_empty_mean_shortfall_renders_dash(tmp_path):
    """Nobody below the floor: mean shortfall is "—" / empty, not $0."""
    base = _ctx()
    empty = floor_summary(add_floor_gap(_universe(25.0, 25.0), FLOOR))
    ctx = base | {"windows": {n: w | {"summary": empty} for n, w in base["windows"].items()}}
    text = write_results(ctx, tmp_path).read_text()
    assert _table_row(text, "Mean shortfall per affected worker, $/hr")[1:] == ["—", "—"]
    fs = pl.read_csv(tmp_path / "floor_summary.csv")
    assert fs.filter(pl.col("measure") == "mean_short_hr")["est"].null_count() == 2


def test_qa_logs_minor_workers(tmp_path):
    write_results(_ctx(), tmp_path)
    assert "## Workers under 18\n\n3 universe records, 30 ± 2 weighted workers." in (tmp_path / "qa.md").read_text()


def test_csvs_written(tmp_path):
    write_results(_ctx(), tmp_path)
    for name in ["floor_summary", "by_industry", "by_cow_class", "leakage", "households", "capacity",
                 "gos_tests", "sensitivities"]:
        assert (tmp_path / f"{name}.csv").stat().st_size > 0


def test_charts_written(tmp_path):
    ctx = _ctx(gos_79=1.0)
    for path in [charts.gap_vs_gos(ctx["windows"]["pool"]["capacity"], LABELS, CFG, tmp_path),
                 charts.wage_distribution(ctx["u"], FLOOR, CFG, tmp_path)]:
        assert path.exists() and path.stat().st_size > 0


def test_crosscheck_section():
    """Section 8 renders survey and OEWS percentiles side by side, and the OEWS share is marked interpolated."""
    q = {k: (10.0 + i, 0.1) for i, k in enumerate(("p10", "p25", "p50", "p75", "p90"))} | {"share_below": (0.4, 0.01)}
    ctx = dict(_ctx()) | {"crosscheck": {
        "metro": {"powpumas": ["02300", "02400"], "mixed": []},
        "oews": {"employment": 1000.0, "p10": 11.0, "p25": 15.0, "p50": 22.0, "p75": 35.0, "p90": 50.0},
        "oews_share_below": 0.42, "survey_orleans": q, "survey_metro": q}}
    md = results_md(ctx)
    assert "## 8. Survey pay vs. employer-reported pay" in md
    assert "42.0% (interpolated)" in md
