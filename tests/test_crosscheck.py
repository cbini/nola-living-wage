import polars as pl
import pytest

from nola_lw.analysis import crosscheck as cc
from nola_lw.config import load_config

CFG = load_config()


def _oews(values: dict[str, str]) -> dict:
    o = CFG["oews"]
    return {"status": "REQUEST_SUCCEEDED", "Results": {"series": [
        {"seriesID": f"OEUM{o['area']}000000000000{dt}", "data": [{"year": str(o["year"]), "value": values[k]}]}
        for k, dt in o["datatypes"].items()]}}


def _cpi(ref: float, target: float) -> dict:
    y_ref, m_ref = CFG["oews"]["reference_month"].split("-")
    y_t, m_t = CFG["cpi"]["target"].split("-")
    return {"Results": {"series": [{"data": [{"year": y_ref, "period": f"M{m_ref}", "value": str(ref)},
                                             {"year": y_t, "period": f"M{m_t}", "value": str(target)}]}]}}


def test_oews_percentiles_in_target_dollars():
    v = {"employment": "1,000", "p10": "10", "p25": "15", "p50": "20", "p75": "30", "p90": "50"}
    p = cc.oews_percentiles(_oews(v), _cpi(100.0, 110.0), CFG)
    assert p["employment"] == 1000
    assert p["p50"] == pytest.approx(22.0)
    assert p["p10"] == pytest.approx(11.0)


def test_oews_missing_year_raises():
    bad = _oews({"employment": "1", "p10": "1", "p25": "2", "p50": "3", "p75": "4", "p90": "5"})
    bad["Results"]["series"][1]["data"] = []
    with pytest.raises(ValueError, match="p10"):
        cc.oews_percentiles(bad, _cpi(100.0, 100.0), CFG)


def test_share_below_interpolates_between_percentiles():
    p = {"p10": 10.0, "p25": 15.0, "p50": 20.0, "p75": 30.0, "p90": 50.0}
    assert cc.share_below(p, 17.5) == pytest.approx(0.375)
    assert cc.share_below(p, 5.0) is None  # outside the published range: unknown, not 0


def test_metro_powpumas_keeps_only_all_metro_powpumas():
    metro = CFG["oews"]["metro_counties"]
    comp = pl.DataFrame({"st": ["22"] * 4, "county": [metro[0], metro[1], metro[2], "001"],
                         "pwst": ["022"] * 4, "powpuma": ["A", "A", "B", "B"]})
    out = cc.metro_powpumas(comp, CFG)
    assert out == {"powpumas": ["A"], "mixed": ["B"]}
