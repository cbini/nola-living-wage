import polars as pl
import pytest

from nola_lw.checkpoint import powpuma_by_year, suppressed_gdp, wage_check, write_report
from nola_lw.config import load_config

CFG = load_config()


def _persons(wagp, powpuma="02400", cow="1"):
    n = len(wagp)
    return pl.DataFrame({"SERIALNO": [f"2022HU{i:07d}" for i in range(n)], "POWSP": ["022"] * n,
                         "POWPUMA": [powpuma] * n, "COW": [cow] * n, "WAGP": wagp,
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
