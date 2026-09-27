import polars as pl
import pytest

from nola_lw.analysis import capacity

PANEL_SCHEMA = {"line": pl.Utf8, "gdp": pl.Float64, "comp": pl.Float64, "tax_ratio": pl.Float64,
                "cfc_share": pl.Float64, "gos": pl.Float64, "gos_low": pl.Float64, "wages": pl.Float64}


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
    out = capacity.capacity_table(gap_by_line, panel_mean)
    row = out.row(0, named=True)
    assert row["self_funding"] == "suppressed"
    assert row["self_funding_low"] == "suppressed"


def test_government_self_funding_is_na():
    panel_mean = pl.DataFrame({"line": ["83"], "gdp": [500.0], "comp": [400.0], "tax_ratio": [0.0],
                               "cfc_share": [None], "gos": [50.0], "gos_low": [0.0], "wages": [None]},
                              schema=PANEL_SCHEMA)
    gap_by_line = pl.DataFrame({"line": ["83"], "gap": [100.0], "gap_se": [5.0]})
    out = capacity.capacity_table(gap_by_line, panel_mean)
    row = out.row(0, named=True)
    assert row["self_funding"] == "n/a"
    assert row["self_funding_low"] == "n/a"


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
