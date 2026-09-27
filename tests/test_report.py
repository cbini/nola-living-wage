import functools

import polars as pl

from nola_lw.analysis import capacity as cap
from nola_lw.analysis.gaps import add_floor_gap, floor_summary, household_table, leakage, summary_by, year_subset
from nola_lw.config import load_config
from nola_lw.fetch.mit import HOUSEHOLD_KEYS
from nola_lw.report import charts
from nola_lw.report.results import headline, write_results

CFG = load_config()
LABELS = {"3": "Agriculture, forestry, fishing and hunting", "79": "Accommodation and food services",
          "83": "Government and government enterprises"}
FLOOR = 20.0
THRESHOLDS = {k: FLOOR + i for i, k in enumerate(HOUSEHOLD_KEYS)}


def _universe(early_wage: float, late_wage: float) -> pl.DataFrame:
    """Two workers per year (hospitality private, government public). Replicate weights alternate
    around the full weight, so SEs are small but nonzero."""
    rows = []
    for y in range(2020, 2025):
        wage = early_wage if y < 2022 else late_wage
        for line, cls, res in [("79", "private", "orleans"), ("83", "public", "other_la"),
                               ("3", "private", "out_of_state")]:
            rows.append({"year": str(y), "bea_line": line, "cow_class": cls, "residence": res, "src": "la",
                         "household": HOUSEHOLD_KEYS[0], "wage_hr": wage, "hours": 2000.0, "earnings": wage * 2000})
    u = pl.DataFrame(rows)
    return u.with_columns(PWGTP=pl.lit(10.0), **{f"PWGTP{i}": pl.lit(10.0 + (-1) ** i * 0.1) for i in range(1, 81)})


def _panel(gos_79: float) -> pl.DataFrame:
    """Line 3 has suppressed compensation (so null GOS), as in BEA CAINC6N 2024."""
    return pl.DataFrame({
        "line": ["3", "79", "83", "total", "private"],
        "gdp": [1e8, 1e9, 1e9, 2e9, 1e9], "comp": [None, 5e8, 8e8, 1.3e9, 5e8],
        "tax_ratio": [0.1, 0.1, 0.0, 0.05, 0.1], "cfc_share": [0.1, 0.1, None, None, None],
        "gos": [None, gos_79, 2e8, 6e8, 4e8], "gos_low": [None, gos_79, 0.0, 4e8, 3e8],
        "wages": [None, None, None, 1e9, None]})


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
    return {"u": u, "windows": windows}


@functools.cache
def _ctx(early_wage=15.0, late_wage=15.0, gos_79=4e8) -> dict:
    base = _survey_windows(early_wage, late_wage)
    u = base["u"]
    windows = {name: w | {"capacity": cap.capacity_table(w["gap_by_line"], _panel(gos_79), "83")}
               for name, w in base["windows"].items()}
    s = windows["pool"]["summary"]
    sens = pl.DataFrame([{"sensitivity": n, "variant": n, "workers_below": s["below"][0], "workers_below_se": 1.0,
                          "total_gap": s["total_gap"][0] * k, "total_gap_se": 1.0, "factor": 1.0}
                         for n, k in [("headline", 1.0), ("hours_rule", 2.0)]])
    qa = {"by_src": [], "outliers": (0, (0.0, 0.0)), "self_employed": (0.0, 0.0),
          "crosswalk": {"pairs_in_data": 2, "crosswalk_rows": 2}, "gos_resid": 0.0,
          "suppressed": pl.DataFrame(), "children_over_cap": (0, (0.0, 0.0))}
    return {"cfg": CFG, "floor": FLOOR, "thresholds": THRESHOLDS, "labels": LABELS, "windows": windows,
            "sensitivities": sens, "survey_bea": {"pct": -0.1, "pct_like": -0.04},
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


def test_headline_flags_window_difference():
    differ, _ = headline(_ctx(early_wage=25.0, late_wage=15.0))
    same, _ = headline(_ctx())
    assert "differ beyond their MOEs on" in differ
    assert "do not differ beyond their MOEs" in same


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
