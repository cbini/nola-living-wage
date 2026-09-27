import polars as pl
import pytest

from nola_lw.analysis import sensitivity
from nola_lw.config import load_config

CFG = load_config()


def _weighted(n, pwgtp):
    return {"PWGTP": pwgtp} | {f"PWGTP{i}": pwgtp for i in range(1, 81)}


def _cpi_json(years: list[int], target: str) -> dict:
    """Flat CPI (value 100 every month) so cpi_factor == 1.0 for every year and `target`."""
    data = []
    for y in years:
        for m in range(1, 13):
            data.append({"year": str(y), "period": f"M{m:02d}", "value": "100.0"})
    ty, tm = target.split("-")
    data.append({"year": ty, "period": f"M{tm}", "value": "100.0"})
    return {"Results": {"series": [{"data": data}]}}


def _bea_cell(table, line, geo, year, value):
    return {"table": table, "line_code": line, "line_desc": "", "geo": geo, "year": year,
            "value": value, "flag": None}


def test_passthrough_zero_p_is_one():
    f = sensitivity.passthrough_factor(lambda f: 10.0 * f, base=100.0, p=0.0, tol=1e-6, max_iter=100)
    assert f == pytest.approx(1.0)


def test_passthrough_fixed_point():
    f = sensitivity.passthrough_factor(lambda f: 10.0 * f, base=100.0, p=0.5, tol=1e-9, max_iter=1000)
    assert f == pytest.approx(1 / (1 - 0.05))


def test_passthrough_diverges_raises():
    with pytest.raises(RuntimeError):
        sensitivity.passthrough_factor(lambda f: 1000.0 * f, base=10.0, p=1.0, tol=1e-6, max_iter=50)


def test_hours_rule_annual_gap():
    df = pl.DataFrame({"earnings": [25_000.0], "hours": [1000.0]})
    out = sensitivity.add_hours_rule_gap(df, floor=20.0, hours_full_time=2080)
    assert out["below"][0] is True
    assert out["gap_yr"][0] == pytest.approx(16_600.0)


def test_sensitivity_rows_complete():
    pool = CFG["years"]["pool"]
    years = list(range(pool[0], pool[1] + 1))
    target = CFG["cpi"]["target"]
    b = CFG["bea"]

    bea_rows = []
    for y in years:
        # sized so the base spending dwarfs the synthetic gap (else the p=1 iteration diverges)
        bea_rows.append(_bea_cell("SAPCE1", "1", b["state_geo"], y, 5_000_000_000.0))
        bea_rows.append(_bea_cell("CAINC1", "1", b["county_geo"], y, 500_000_000.0))
        bea_rows.append(_bea_cell("SAINC1", "1", b["state_geo"], y, 5_000_000_000.0))
        bea_rows.append(_bea_cell("CAGDP2", "1", b["county_geo"], y, 5_000_000_000.0))
    schema = {"table": pl.Utf8, "line_code": pl.Utf8, "line_desc": pl.Utf8, "geo": pl.Utf8,
              "year": pl.Int64, "value": pl.Float64, "flag": pl.Utf8}
    bea = pl.DataFrame(bea_rows, schema=schema)
    bea_ctx = {"bea": bea, "cpi_json": _cpi_json(years, target)}

    n = len(years)
    u = pl.DataFrame({
        "year": [str(y) for y in years],
        "residence": ["orleans", "other_la", "out_of_state"] + ["orleans"] * (n - 3),
        "outlier": [False, False, True] + [False] * (n - 3),
        "earnings": [15_000.0 + 1000 * i for i in range(n)],
        "hours": [2000.0] * n,
        "wage_hr": [(15_000.0 + 1000 * i) / 2000.0 for i in range(n)],
    } | _weighted(n, [10.0] * n))

    out = sensitivity.run_sensitivities(u, bea_ctx, CFG, u_self=u)
    assert out.height == 13
    assert set(out.columns) == {"sensitivity", "variant", "workers_below", "workers_below_se",
                                "total_gap", "total_gap_se", "factor"}
    names = out["sensitivity"].to_list()
    assert names.count("headline") == 1
    assert names.count("passthrough") == 6
    assert names.count("outliers_included") == 1
    assert names.count("hours_rule") == 1
    assert names.count("la_residents_only") == 1
    assert names.count("years_2022_2024") == 1
    assert names.count("metro_thresholds") == 1
    assert names.count("self_employed_included") == 1

    variants = set(out.filter(pl.col("sensitivity") == "passthrough")["variant"].to_list())
    assert variants == {"p=0 base=resident_pce", "p=0 base=gdp",
                        "p=0.5 base=resident_pce", "p=0.5 base=gdp",
                        "p=1 base=resident_pce", "p=1 base=gdp"}

    headline = out.filter(pl.col("sensitivity") == "headline").row(0, named=True)
    p0 = out.filter(pl.col("variant") == "p=0 base=resident_pce").row(0, named=True)
    assert p0["factor"] == pytest.approx(1.0)
    assert p0["total_gap"] == pytest.approx(headline["total_gap"])
    assert p0["workers_below"] == pytest.approx(headline["workers_below"])
