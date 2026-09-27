from pathlib import Path

import pytest

from nola_lw.config import load_config
from nola_lw.fetch.bea import parse_bea_csv

FIX = Path(__file__).parent / "fixtures" / "bea_sample.csv"
CFG = load_config()


def _parse(path=FIX, geo="22071"):
    return parse_bea_csv(path, geo, CFG["bea"])


def test_parse_suppressed():
    df = _parse()
    r = df.filter((df["line_code"] == "200") & (df["year"] == 2024)).row(0, named=True)
    assert r["value"] is None
    assert r["flag"] == "(D)"


def test_parse_numbers_and_units():
    df = _parse()
    r = df.filter((df["line_code"] == "50") & (df["year"] == 2020)).row(0, named=True)
    assert r["value"] == 11_644_740 * 1000
    assert r["flag"] is None
    assert r["table"] == "CAINC5N"


def test_footer_dropped():
    df = _parse()
    assert set(df["line_code"]) == {"10", "50", "200"}
    assert df["geo"].null_count() == 0


def test_geo_filter():
    assert set(_parse()["geo"]) == {"22071"}
    assert set(_parse(geo="22000")["geo"]) == {"22000"}


def test_millions_scaled(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text('GeoFIPS,GeoName,Region,TableName,LineCode,IndustryClassification,Description,Unit,2024\n'
                 ' "22000","Louisiana",5,SAGDP2,1,"...","All industry total","Millions of current dollars",2.5\n'
                 '"U.S. Bureau of Economic Analysis"\n')
    assert _parse(p, "22000")["value"][0] == 2_500_000


def test_unknown_unit_raises(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text('GeoFIPS,GeoName,Region,TableName,LineCode,IndustryClassification,Description,Unit,2024\n'
                 ' "22000","Louisiana",5,SAGDP9,1,"...","Real GDP","Millions of chained 2017 dollars",2.5\n')
    with pytest.raises(ValueError, match="unit"):
        _parse(p, "22000")


def test_table_file_falls_back_to_all_areas(tmp_path):
    from nola_lw.fetch.bea import _table_file
    (tmp_path / "SAINC").mkdir()
    f = tmp_path / "SAINC" / "SAINC1__ALL_AREAS_1929_2025.csv"
    f.write_text("")
    (tmp_path / "SAINC" / "SAINC11_LA_1999_2025.csv").write_text("")
    assert _table_file(tmp_path, "SAINC1", "LA") == f
