import polars as pl
import pytest

from nola_lw.build import universe as u
from nola_lw.config import load_config

CFG = load_config()


def _persons(**over):
    n = over.pop("n", 1)
    base = {
        "SERIALNO": [f"2022HU{i:07d}" for i in range(n)],
        "SPORDER": ["1"] * n,
        "POWSP": ["022"] * n,
        "POWPUMA": ["02400"] * n,
        "COW": ["1"] * n,
        "WAGP": [41_600] * n,
        "ADJINC": [1_050_000] * n,
        "WKHP": [40] * n,
        "WKWN": [52] * n,
        "STATE": ["22"] * n,
        "PUMA": ["02402"] * n,
        "PWGTP": [1] * n,
    } | {f"PWGTP{i}": [1] * n for i in range(1, 81)}
    for k, v in over.items():
        base[k] = v if isinstance(v, list) else [v] * n
    return pl.DataFrame(base)


def test_universe_filters(monkeypatch):
    monkeypatch.setattr(u, "cpi_factor", lambda *a, **k: 1.0)
    df = pl.concat([
        _persons(),
        _persons(POWPUMA="01500"),
        _persons(COW="6"),
        _persons(WKHP=0),
        _persons(WKWN=0),
        _persons(WAGP=0),
    ])
    out = u.build_universe(df, {}, CFG)
    assert out.height == 1


def test_self_employed_included(monkeypatch):
    """Sensitivity universe: self-employed (COW 6-7) join, paid on wages plus self-employment income."""
    monkeypatch.setattr(u, "cpi_factor", lambda *a, **k: 1.0)
    df = pl.concat([
        _persons(SEMP=0),
        _persons(COW="6", WAGP=0, SEMP=20_800),
        _persons(COW="7", WAGP=10_000, SEMP=10_400),
        _persons(COW="6", WAGP=0, SEMP=-5_000),
        _persons(COW="8", WAGP=0, SEMP=0),
    ])
    assert u.build_universe(df, {}, CFG).height == 1
    out = u.build_universe(df, {}, CFG, include_self_employed=True).sort("COW")
    assert out["COW"].to_list() == ["1", "6", "7"]
    assert out["earnings"].to_list() == pytest.approx([41_600 * 1.05, 20_800 * 1.05, 20_400 * 1.05])


def test_wage_hr(monkeypatch):
    monkeypatch.setattr(u, "cpi_factor", lambda *a, **k: 1.0278)
    out = u.build_universe(_persons(), {}, CFG)
    assert out["wage_hr"][0] == pytest.approx(41_600 * 1.05 * 1.0278 / 2080)


def test_outlier_flag(monkeypatch):
    monkeypatch.setattr(u, "cpi_factor", lambda *a, **k: 1.0)
    df = pl.concat([
        _persons(WAGP=1.50 * 2080, ADJINC=1_000_000),
        _persons(WAGP=600.0 * 2080, ADJINC=1_000_000),
        _persons(WAGP=20.0 * 2080, ADJINC=1_000_000),
    ])
    out = u.build_universe(df, {}, CFG).sort("wage_hr")
    assert out["outlier"].to_list() == [True, False, True]


def test_residence_tags(monkeypatch):
    monkeypatch.setattr(u, "cpi_factor", lambda *a, **k: 1.0)
    df = pl.concat([
        _persons(PUMA="02402", STATE="22"),
        _persons(PUMA="01500", STATE="22"),
        _persons(PUMA="02402", STATE="28"),
    ])
    out = u.build_universe(df, {}, CFG)
    assert out["residence"].to_list() == ["orleans", "other_la", "out_of_state"]


def test_self_employed_count():
    df = pl.DataFrame({
        "POWSP": ["022", "022"], "POWPUMA": ["02400", "02400"], "COW": ["6", "1"],
        "PWGTP": [5, 100],
    } | {f"PWGTP{i}": [5, 100] for i in range(1, 81)})
    est, se = u.self_employed_count(df, CFG)
    assert est == pytest.approx(5)
    assert se == pytest.approx(0)


def test_load_persons_reports_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="psam_p22.csv"):
        u.load_persons(CFG, tmp_path)
