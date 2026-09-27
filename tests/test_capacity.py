import polars as pl
import pytest

from nola_lw.analysis import capacity
from nola_lw.config import load_config

PANEL_SCHEMA = {"line": pl.Utf8, "gdp": pl.Float64, "comp": pl.Float64, "tax_ratio": pl.Float64,
                "cfc_share": pl.Float64, "gos": pl.Float64, "gos_low": pl.Float64, "wages": pl.Float64}
CFG = load_config()


def _cpi_json(month_values: dict[str, float]) -> dict:
    data = []
    for key, val in month_values.items():
        year, period = key.split("-")
        data.append({"year": year, "period": f"M{period}", "value": str(val)})
    return {"Results": {"series": [{"data": data}]}}


def test_gos_identity():
    assert capacity.gos(100.0, 60.0, 0.1) == pytest.approx(30.0)


def test_suppressed_comp_gives_unknown_not_pass():
    panel_mean = pl.DataFrame({"line": ["6"], "gdp": [100.0], "comp": [None], "tax_ratio": [None],
                               "cfc_share": [None], "gos": [None], "gos_low": [None], "wages": [None]},
                              schema=PANEL_SCHEMA)
    gap_by_line = pl.DataFrame({"line": ["6"], "gap": [10.0], "gap_se": [1.0]})
    out = capacity.capacity_table(gap_by_line, panel_mean, "83")
    row = out.row(0, named=True)
    assert row["self_funding"] == "suppressed"
    assert row["self_funding_low"] == "suppressed"


def test_government_self_funding_is_na():
    panel_mean = pl.DataFrame({"line": ["83"], "gdp": [500.0], "comp": [400.0], "tax_ratio": [0.0],
                               "cfc_share": [None], "gos": [50.0], "gos_low": [0.0], "wages": [None]},
                              schema=PANEL_SCHEMA)
    gap_by_line = pl.DataFrame({"line": ["83"], "gap": [100.0], "gap_se": [5.0]})
    out = capacity.capacity_table(gap_by_line, panel_mean, "83")
    row = out.row(0, named=True)
    assert row["self_funding"] == "n/a"
    assert row["self_funding_low"] == "n/a"


def test_no_sample_line_is_not_fail():
    """A line with a null gap (no PUMS-sampled worker after the left join) is its own state, not
    silently treated as "fail"."""
    panel_mean = pl.DataFrame({"line": ["6"], "gdp": [100.0], "comp": [60.0], "tax_ratio": [0.1],
                               "cfc_share": [0.1], "gos": [30.0], "gos_low": [20.0], "wages": [None]},
                              schema=PANEL_SCHEMA)
    gap_by_line = pl.DataFrame({"line": [], "gap": [], "gap_se": []},
                               schema={"line": pl.Utf8, "gap": pl.Float64, "gap_se": pl.Float64})
    out = capacity.capacity_table(gap_by_line, panel_mean, "83")
    row = out.row(0, named=True)
    assert row["gap"] is None
    assert row["self_funding"] == "no sample"
    assert row["self_funding_low"] == "no sample"


def test_nonpositive_denominator_nulls_the_ratio_not_inf():
    """gap/gos comes back null, not inf or sign-inverted, when gos <= 0 (self_funding still fails)."""
    panel_mean = pl.DataFrame({"line": ["76"], "gdp": [500.0], "comp": [600.0], "tax_ratio": [0.0],
                               "cfc_share": [0.2], "gos": [-100.0], "gos_low": [-200.0], "wages": [None]},
                              schema=PANEL_SCHEMA)
    gap_by_line = pl.DataFrame({"line": ["76"], "gap": [10.0], "gap_se": [1.0]})
    out = capacity.capacity_table(gap_by_line, panel_mean, "83")
    row = out.row(0, named=True)
    assert row["gap_gos"] is None
    assert row["gap_gos_low"] is None
    assert row["gap_gos_se"] is None
    assert row["self_funding"] == "fail"
    assert row["self_funding_low"] == "fail"


def test_zero_denominator_nulls_the_ratio_not_inf():
    panel_mean = pl.DataFrame({"line": ["83"], "gdp": [500.0], "comp": [400.0], "tax_ratio": [0.0],
                               "cfc_share": [None], "gos": [50.0], "gos_low": [0.0], "wages": [None]},
                              schema=PANEL_SCHEMA)
    gap_by_line = pl.DataFrame({"line": ["83"], "gap": [100.0], "gap_se": [5.0]})
    out = capacity.capacity_table(gap_by_line, panel_mean, "83")
    row = out.row(0, named=True)
    assert row["gap_gos_low"] is None
    assert row["gap_gos_low_se"] is None


def test_capacity_table_has_ratio_ses():
    panel_mean = pl.DataFrame({"line": ["11"], "gdp": [1000.0], "comp": [600.0], "tax_ratio": [0.1],
                               "cfc_share": [0.1], "gos": [300.0], "gos_low": [200.0], "wages": [None]},
                              schema=PANEL_SCHEMA)
    gap_by_line = pl.DataFrame({"line": ["11"], "gap": [30.0], "gap_se": [3.0]})
    out = capacity.capacity_table(gap_by_line, panel_mean, "83")
    row = out.row(0, named=True)
    assert row["gap_gdp_se"] == pytest.approx(3.0 / 1000.0)
    assert row["gap_comp_se"] == pytest.approx(3.0 / 600.0)
    assert row["gap_gos_se"] == pytest.approx(3.0 / 300.0)
    assert row["gap_gos_low_se"] == pytest.approx(3.0 / 200.0)
    assert row["gap_wages_se"] is None


def test_bea_converted_to_target_dollars():
    panel = pl.DataFrame({"line": ["total", "total"], "year": [2020, 2024], "gdp": [100.0, 100.0],
                          "comp": [0.0, 0.0], "tax_ratio": [0.0, 0.0], "cfc_share": [None, None],
                          "gos": [100.0, 100.0], "gos_low": [100.0, 100.0], "wages": [None, None]},
                         schema=PANEL_SCHEMA | {"year": pl.Int64})
    months = {f"2020-{i:02d}": 80.0 for i in range(1, 13)} | {f"2024-{i:02d}": 100.0 for i in range(1, 13)}
    months["2025-06"] = 110.0
    cpi_json = _cpi_json(months)
    cfg = {"cpi": {"target": "2025-06"}}
    out = capacity.to_target_dollars(panel, cpi_json, cfg).sort("year")
    assert out["gdp"].to_list() == pytest.approx([137.5, 110.0])
    assert out["gos"].to_list() == pytest.approx([137.5, 110.0])


def test_window_mean_null_if_any_year_null():
    panel = pl.DataFrame({"line": ["1", "1"], "year": [2020, 2021], "gdp": [100.0, None]},
                         schema={"line": pl.Utf8, "year": pl.Int64, "gdp": pl.Float64})
    out = capacity.window_mean(panel, [2020, 2021])
    assert out["gdp"][0] is None


def test_validate_gos_method_raises_beyond_tol():
    cfg = {"bea": {"state_geo": "22000"}, "years": {"pool": [2020, 2020]},
          "capacity": {"gos_validation_tol_usd": 500000}}
    bea = pl.DataFrame({
        "table": ["SAGDP2", "SAGDP3", "SAGDP4", "SAGDP7"],
        "line_code": ["1", "1", "1", "1"],
        "geo": ["22000"] * 4,
        "year": [2020] * 4,
        "value": [10_000_000.0, 100.0, 100.0, 100.0],
        "flag": [None, None, None, None],
    })
    with pytest.raises(ValueError, match="exceeds tolerance"):
        capacity.validate_gos_method(bea, cfg)


def test_validate_gos_method_within_tol():
    cfg = {"bea": {"state_geo": "22000"}, "years": {"pool": [2020, 2020]},
          "capacity": {"gos_validation_tol_usd": 500000}}
    bea = pl.DataFrame({
        "table": ["SAGDP2", "SAGDP3", "SAGDP4", "SAGDP7"],
        "line_code": ["1", "1", "1", "1"],
        "geo": ["22000"] * 4,
        "year": [2020] * 4,
        "value": [300.0, 100.0, 100.0, 100.0],
        "flag": [None, None, None, None],
    })
    assert capacity.validate_gos_method(bea, cfg) == pytest.approx(0.0)


def test_validate_gos_method_raises_on_flagged_cell():
    cfg = {"bea": {"state_geo": "22000"}, "years": {"pool": [2020, 2020]},
          "capacity": {"gos_validation_tol_usd": 500000}}
    bea = pl.DataFrame({
        "table": ["SAGDP2", "SAGDP3", "SAGDP4", "SAGDP7"],
        "line_code": ["1", "1", "1", "1"],
        "geo": ["22000"] * 4,
        "year": [2020] * 4,
        "value": [300.0, 100.0, 100.0, 100.0],
        "flag": ["(D)", None, None, None],
    })
    with pytest.raises(ValueError, match="suppressed"):
        capacity.validate_gos_method(bea, cfg)


def _bea_cell(table, line, geo, year, value, flag=None):
    return {"table": table, "line_code": line, "line_desc": "", "geo": geo, "year": year,
            "value": value, "flag": flag}


def test_bea_panel_suppression_gov_and_total_private_arithmetic():
    """D6: a flagged CAINC6N cell makes comp/gos/gos_low null for that line and "suppressed" once
    it reaches capacity_table. Also checks gov-line gos_low == 0 and the total/private gos_low
    arithmetic (D4)."""
    cfg = {"bea": {"county_geo": "C", "state_geo": "S", "national_geo": "N",
                   "wages_line": {"table": "CAINC5N", "line": "50"}},
          "capacity": {"total_line": "T", "private_line": "P",
                       "cainc6n_total": ["100"], "cainc6n_private": ["100"]},
          "years": {"pool": [2020, 2020]},
          "crosswalk": {"gov_line": "83"}}
    industries = pl.DataFrame({"line": ["A", "83"], "cainc6n_lines": ["10", "20"], "fa_line": ["5", ""]})

    bea_rows = [
        _bea_cell("CAGDP2", "A", "C", 2020, 1000.0),
        _bea_cell("CAGDP2", "83", "C", 2020, 2000.0),
        _bea_cell("CAGDP2", "T", "C", 2020, 3000.0),
        _bea_cell("CAGDP2", "P", "C", 2020, 1000.0),
        _bea_cell("CAINC6N", "10", "C", 2020, None, "(D)"),  # suppressed comp for line A
        _bea_cell("CAINC6N", "20", "C", 2020, 800.0),
        _bea_cell("CAINC6N", "100", "C", 2020, 1000.0),
        _bea_cell("CAINC5N", "50", "C", 2020, 900.0),
        _bea_cell("SAGDP2", "A", "S", 2020, 500.0), _bea_cell("SAGDP3", "A", "S", 2020, 50.0),
        _bea_cell("SAGDP2", "83", "S", 2020, 1000.0), _bea_cell("SAGDP3", "83", "S", 2020, 100.0),
        _bea_cell("SAGDP2", "T", "S", 2020, 1500.0), _bea_cell("SAGDP3", "T", "S", 2020, 150.0),
        _bea_cell("SAGDP2", "P", "S", 2020, 500.0), _bea_cell("SAGDP3", "P", "S", 2020, 50.0),
        _bea_cell("SAGDP2", "A", "N", 2020, 1000.0),
    ]
    schema = {"table": pl.Utf8, "line_code": pl.Utf8, "line_desc": pl.Utf8, "geo": pl.Utf8,
              "year": pl.Int64, "value": pl.Float64, "flag": pl.Utf8}
    bea = pl.DataFrame(bea_rows, schema=schema)
    fa = pl.DataFrame({"table": ["FAAt304ESI"], "line_code": ["5"], "line_desc": [""],
                       "year": [2020], "value": [200.0], "flag": [None]})

    panel = capacity.bea_panel(bea, fa, industries, cfg)

    line_a = panel.filter(pl.col("line") == "A").row(0, named=True)
    assert line_a["comp"] is None
    assert line_a["gos"] is None
    assert line_a["gos_low"] is None

    gov = panel.filter(pl.col("line") == "83").row(0, named=True)
    assert gov["gos"] == pytest.approx(2000.0 - 800.0 - 2000.0 * 0.1)  # 1000.0
    assert gov["gos_low"] == pytest.approx(0.0)

    # line-A term (gdp * cfc_share) = 1000 * (200/1000) = 200, independent of its suppressed comp
    total = panel.filter(pl.col("line") == "total").row(0, named=True)
    t_gos = 3000.0 - 1000.0 - 3000.0 * 0.1  # 1700.0
    assert total["gos"] == pytest.approx(t_gos)

    private = panel.filter(pl.col("line") == "private").row(0, named=True)
    p_gos = 1000.0 - 1000.0 - 1000.0 * 0.1  # -100.0
    assert private["gos"] == pytest.approx(p_gos)
    assert private["gos_low"] == pytest.approx(p_gos - 200.0)
    # total lower bound = private lower bound + government lower bound (0); not total GOS less CFC,
    # which can undercut the private bound because total/private use different aggregate tax ratios
    assert total["gos_low"] == pytest.approx(private["gos_low"] + gov["gos_low"])

    pool_mean = capacity.window_mean(panel, [2020])
    gbl = pl.DataFrame({"line": ["A", "83", "total", "private"], "gap": [5.0, 5.0, 5.0, 5.0],
                        "gap_se": [1.0, 1.0, 1.0, 1.0]})
    table = capacity.capacity_table(gbl, pool_mean, "83")
    assert table.filter(pl.col("line") == "A")["self_funding"][0] == "suppressed"
    assert table.filter(pl.col("line") == "A")["self_funding_low"][0] == "suppressed"
    assert table.filter(pl.col("line") == "83")["self_funding"][0] == "n/a"


def test_gap_by_line_uses_config_private_classes():
    u = pl.DataFrame({
        "bea_line": ["11", "11", "83"],
        "cow_class": ["private", "nonprofit", "public"],
        "wage_hr": [10.0, 10.0, 10.0], "hours": [2000.0, 2000.0, 2000.0],
        "below": [True, True, True], "gap_hr": [5.0, 5.0, 5.0], "gap_yr": [10000.0, 10000.0, 10000.0],
        "PWGTP": [1, 1, 1],
    } | {f"PWGTP{i}": [1, 1, 1] for i in range(1, 81)})
    out = capacity.gap_by_line(u, CFG)
    private_row = out.filter(pl.col("line") == "private").row(0, named=True)
    assert private_row["gap"] == pytest.approx(20000.0)  # the two private/nonprofit workers only


def test_gos_tests_nulls_ratio_for_nonpositive_denominator():
    cfg = {"crosswalk": {"gov_line": "83"}, "capacity": {"imputed_rent_line": "56", "employer_payroll_tax_rate": 0.0},
           "universe": {"cow_class": {"1": "private", "2": "nonprofit", "3": "public"}}}
    u = pl.DataFrame({
        "cow_class": ["private", "public"], "bea_line": ["11", "83"],
        "wage_hr": [10.0, 10.0], "hours": [2000.0, 2000.0],
        "below": [True, True], "gap_hr": [5.0, 5.0], "gap_yr": [10000.0, 10000.0],
        "PWGTP": [1, 1],
    } | {f"PWGTP{i}": [1, 1] for i in range(1, 81)})
    panel_mean = pl.DataFrame({"line": ["private", "total", "83", "56"], "gos": [-1.0, 100.0, None, None],
                               "gos_low": [10.0, -5.0, None, None], "comp": [None, None, 0.0, None]},
                              schema={"line": pl.Utf8, "gos": pl.Float64, "gos_low": pl.Float64, "comp": pl.Float64})
    out = capacity.gos_tests(u, panel_mean, cfg)
    assert out["private_upper"] == (None, None)  # private gos <= 0
    assert out["total_lower"] == (None, None)  # total gos_low <= 0
    assert out["government"] == (None, None)  # gov comp <= 0
    assert out["private_lower"][0] is not None
    assert out["private_lower_ex"] == (None, None)  # imputed-rent line GOS suppressed


def test_zero_gap_passes_both_bounds():
    """Nothing to fund: a zero gap passes even when GOS is <= 0."""
    panel_mean = pl.DataFrame({"line": ["64"], "gdp": [500.0], "comp": [400.0], "tax_ratio": [0.0],
                               "cfc_share": [0.5], "gos": [100.0], "gos_low": [-150.0], "wages": [None]},
                              schema=PANEL_SCHEMA)
    gap_by_line = pl.DataFrame({"line": ["64"], "gap": [0.0], "gap_se": [0.0]})
    row = capacity.capacity_table(gap_by_line, panel_mean, "83").row(0, named=True)
    assert (row["self_funding"], row["self_funding_low"]) == ("pass", "pass")


def test_zero_gap_with_suppressed_gos_stays_suppressed():
    """Suppressed is unknown, never a pass, even when the survey gap is zero."""
    panel_mean = pl.DataFrame({"line": ["6"], "gdp": [500.0], "comp": [None], "tax_ratio": [0.0],
                               "cfc_share": [0.5], "gos": [None], "gos_low": [None], "wages": [None]},
                              schema=PANEL_SCHEMA)
    gap_by_line = pl.DataFrame({"line": ["6"], "gap": [0.0], "gap_se": [0.0]})
    row = capacity.capacity_table(gap_by_line, panel_mean, "83").row(0, named=True)
    assert (row["self_funding"], row["self_funding_low"]) == ("suppressed", "suppressed")


def test_gos_tests_ex_imputed_rent_line():
    """Ex-real-estate tests drop the line's gap from the numerator and its GOS from the denominator."""
    cfg = {"crosswalk": {"gov_line": "83"}, "capacity": {"imputed_rent_line": "56", "employer_payroll_tax_rate": 0.0},
           "universe": {"cow_class": {"1": "private", "3": "public"}}}
    u = pl.DataFrame({
        "cow_class": ["private", "private", "public"], "bea_line": ["11", "56", "83"],
        "wage_hr": [10.0] * 3, "hours": [2000.0] * 3,
        "below": [True] * 3, "gap_hr": [5.0] * 3, "gap_yr": [10000.0, 30000.0, 10000.0],
        "PWGTP": [1, 1, 1],
    } | {f"PWGTP{i}": [1, 1, 1] for i in range(1, 81)})
    panel_mean = pl.DataFrame({"line": ["private", "total", "83", "56"], "gos": [400e3, 500e3, 1.0, 100e3],
                               "gos_low": [300e3, 300e3, 0.0, 200e3], "comp": [None, None, 1e6, None]},
                              schema={"line": pl.Utf8, "gos": pl.Float64, "gos_low": pl.Float64, "comp": pl.Float64})
    out = capacity.gos_tests(u, panel_mean, cfg)
    assert out["private_upper"][0] == pytest.approx(40e3 / 400e3)
    assert out["private_upper_ex"][0] == pytest.approx(10e3 / 300e3)
    assert out["private_lower_ex"][0] == pytest.approx(10e3 / 100e3)
    assert out["total_upper_ex"][0] == pytest.approx(20e3 / 400e3)
    assert out["total_lower_ex"][0] == pytest.approx(20e3 / 100e3)


def test_capacity_table_loads_employer_payroll_tax_except_wages():
    """Employer cost = gap * (1 + load) against GDP, comp and GOS (and the pass/fail test); wages stay unloaded."""
    panel_mean = pl.DataFrame({"line": ["64"], "gdp": [1000.0], "comp": [500.0], "tax_ratio": [0.0],
                               "cfc_share": [0.0], "gos": [105.0], "gos_low": [105.0], "wages": [400.0]},
                              schema=PANEL_SCHEMA)
    gap_by_line = pl.DataFrame({"line": ["64"], "gap": [100.0], "gap_se": [10.0]})
    row = capacity.capacity_table(gap_by_line, panel_mean, "83", load=0.1).row(0, named=True)
    assert row["cost"] == pytest.approx(110.0)
    assert row["gap_gdp"] == pytest.approx(0.11) and row["gap_gdp_se"] == pytest.approx(0.011)
    assert row["gap_comp"] == pytest.approx(0.22)
    assert row["gap_gos"] == pytest.approx(110.0 / 105.0)
    assert row["gap_wages"] == pytest.approx(0.25) and row["gap_wages_se"] == pytest.approx(0.025)
    assert row["self_funding"] == "fail"  # 100 <= 105 but 110 > 105


def test_gos_tests_load_employer_payroll_tax():
    cfg = {"crosswalk": {"gov_line": "83"}, "capacity": {"imputed_rent_line": "56", "employer_payroll_tax_rate": 0.1},
           "universe": {"cow_class": {"1": "private", "3": "public"}}}
    u = pl.DataFrame({
        "cow_class": ["private", "public"], "bea_line": ["11", "83"],
        "wage_hr": [10.0] * 2, "hours": [2000.0] * 2,
        "below": [True] * 2, "gap_hr": [5.0] * 2, "gap_yr": [10000.0, 10000.0],
        "PWGTP": [1, 1],
    } | {f"PWGTP{i}": [1, 1] for i in range(1, 81)})
    panel_mean = pl.DataFrame({"line": ["private", "total", "83", "56"], "gos": [100e3, 100e3, 1.0, 1.0],
                               "gos_low": [50e3, 50e3, 0.0, 0.0], "comp": [None, None, 1e6, None]},
                              schema={"line": pl.Utf8, "gos": pl.Float64, "gos_low": pl.Float64, "comp": pl.Float64})
    out = capacity.gos_tests(u, panel_mean, cfg)
    assert out["private_upper"][0] == pytest.approx(11e3 / 100e3)
    assert out["total_lower"][0] == pytest.approx(22e3 / 50e3)
    assert out["government"][0] == pytest.approx(11e3 / 1e6)
