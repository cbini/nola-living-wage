import polars as pl
import pytest

from nola_lw.checkpoint import powpuma_by_year, suppressed_gdp, wage_check, write_report
from nola_lw.config import load_config

CFG = load_config()


def _persons(wagp, powpuma="02400", cow="1"):
    n = len(wagp)
    return pl.DataFrame({"SERIALNO": [f"2022HU{i:07d}" for i in range(n)], "POWSP": ["022"] * n,
                         "POWPUMA": [powpuma] * n, "COW": [cow] * n, "WAGP": wagp,
                         "WKHP": [40] * n, "WKWN": [52] * n,
                         "ADJINC": [1_000_000] * n, "PWGTP": [1] * n} | {f"PWGTP{i}": [1] * n for i in range(1, 81)})


def test_wage_check_flag():
    r = wage_check(_persons([80]), 100.0, CFG)
    assert r["survey"] == pytest.approx(80)
    assert r["pct_diff"] == pytest.approx(-0.20)
    assert r["flag"] is True
    assert wage_check(_persons([90]), 100.0, CFG)["flag"] is False


def test_wage_check_universe():
    df = pl.concat([_persons([50]), _persons([1000], powpuma="01900"), _persons([1000], cow="6"),
                    _persons([0])])
    assert wage_check(df, 100.0, CFG)["survey"] == pytest.approx(50)


def test_powpuma_by_year():
    df = pl.concat([_persons([1, 1]), _persons([1], powpuma="01900")]).with_columns(
        SERIALNO=pl.Series(["2020HU1", "2020HU2", "2024HU3"]))
    out = powpuma_by_year(df, "022").sort("year", "POWPUMA")
    assert out.rows() == [("2020", "02400", 2), ("2024", "01900", 1)]


def _gdp(year, cells):
    return pl.DataFrame([{"table": "CAGDP2", "line_code": l, "line_desc": "", "geo": "22071", "year": year,
                          "value": v, "flag": f} for l, v, f in cells],
                        schema={"table": pl.Utf8, "line_code": pl.Utf8, "line_desc": pl.Utf8, "geo": pl.Utf8,
                                "year": pl.Int64, "value": pl.Float64, "flag": pl.Utf8})


def test_suppressed_residual():
    df = _gdp(2024, [("1", 100.0, None), ("3", 30.0, None), ("6", 50.0, None), ("10", None, "(D)")])
    r = suppressed_gdp(df, total_line="1", sector_lines=["3", "6", "10"]).row(0, named=True)
    assert r["residual"] == pytest.approx(20)
    assert r["share"] == pytest.approx(0.20)
    assert r["n_suppressed"] == 1


def test_report_marks_blocked(tmp_path):
    text = write_report(CFG, raw=tmp_path / "raw", out=tmp_path / "out").read_text()
    assert "BLOCKED" in text
    assert "CAINC5N" in text


def test_report_without_cpi_blocks_only_the_comparison(tmp_path, monkeypatch):
    import nola_lw.checkpoint as cp
    monkeypatch.setattr(cp, "_load_persons", lambda raw, cfg: (_persons([80]), []))
    bea = _gdp(2024, [("50", 100.0, None)]).with_columns(table=pl.lit("CAINC5N"))
    monkeypatch.setattr(cp, "load_bea", lambda cfg, raw: bea)
    text = cp._section_wages(_persons([80]), bea, None, CFG)
    assert "$80 ± 0" in text
    assert "BLOCKED" in text and "CUUR0300SA0" in text
    assert "difference |" not in text


def test_commute_flows_share_by_residence_group():
    from nola_lw.checkpoint import commute_flows
    df = pl.DataFrame({"SERIALNO": ["2020HU1", "2020HU2", "2020HU3", "2020HU4"], "STATE": ["22"] * 4,
                       "PUMA": ["02401", "02402", "02301", "02301"], "POWSP": ["022"] * 4,
                       "POWPUMA": ["02400", "01500", "02400", "02390"], "PWGTP": [3, 1, 1, 1]})
    out = commute_flows(df, "22", "022", "02400").sort("res_group").rows(named=True)
    assert out[0]["res_group"] == "023" and out[0]["share"] == pytest.approx(0.5)
    assert out[1]["res_group"] == "024" and out[1]["share"] == pytest.approx(0.75)


def test_price_basis_mismatch_flagged(tmp_path):
    from nola_lw.checkpoint import _section_mit, basis_month
    assert basis_month("December 2025") == "2025-12"
    area = CFG["mit"]["county_path"].replace("/", "_")
    (tmp_path / f"mit_{area}_2027-02-01.csv").write_text(
        "area,household,adults,working,children,hourly,price_basis,fetched\n"
        f"{area},a1_w1_c0,1,1,0,21.00,December 2026,2027-02-01\n")
    assert "MISMATCH" in _section_mit(tmp_path, CFG)


def test_load_persons_file_names_from_config(tmp_path):
    from nola_lw.checkpoint import _load_persons
    import copy
    cfg = copy.deepcopy(CFG)
    cfg["pums"]["bulk_state_fips"] = {"la": "22", "ms": "99"}
    _, missing = _load_persons(tmp_path, cfg)
    assert any("psam_p99.csv" in m for m in missing)


def test_wage_check_like_for_like_includes_owner_salaries():
    df = pl.concat([_persons([50]), _persons([30], cow="7"), _persons([1000], cow="6")])
    assert wage_check(df, 100.0, CFG)["survey"] == pytest.approx(50)
    r = wage_check(df, 100.0, CFG, cow=CFG["checkpoint"]["wage_check_cow_bea"])
    assert r["survey"] == pytest.approx(80)
