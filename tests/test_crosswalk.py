from pathlib import Path

import polars as pl
import pytest

from nola_lw.build import universe as u
from nola_lw.build.crosswalk import apply_crosswalk, draft_crosswalk
from nola_lw.config import load_config
from nola_lw.fetch.bea import load_bea

CFG = load_config()
XW_PATH = Path("crosswalks/cow_naicsp_to_bea.csv")
INDUSTRIES_PATH = Path("crosswalks/bea_industries.csv")


def _pairs(rows):
    return pl.DataFrame({"COW": [c for c, _ in rows], "NAICSP": [n for _, n in rows]})


def test_public_cow_maps_to_government():
    out = draft_crosswalk(_pairs([("4", "6111")]), CFG)
    assert out["bea_line"].to_list() == ["83"]


def test_nonprofit_stays_in_industry():
    out = draft_crosswalk(_pairs([("2", "622M")]), CFG)
    assert out["bea_line"].to_list() == ["70"]


def test_not_specified_codes():
    out = draft_crosswalk(_pairs([("1", "3MS"), ("1", "4MS")]), CFG).sort("NAICSP")
    assert out["bea_line"].to_list() == ["12", "35"]


def test_unmapped_prefix_raises():
    with pytest.raises(ValueError, match="unmapped"):
        draft_crosswalk(_pairs([("1", "99XX")]), CFG)


def test_private_public_admin_raises():
    with pytest.raises(ValueError, match="public-administration"):
        draft_crosswalk(_pairs([("1", "928110")]), CFG)


def test_unmapped_pair_raises():
    u_df = pl.DataFrame({"COW": ["1"], "NAICSP": ["6111"]})
    xw = pl.DataFrame({"COW": ["2"], "NAICSP": ["6111"], "bea_line": ["70"]})
    with pytest.raises(ValueError, match=r"missing.*\(1, 6111\)"):
        apply_crosswalk(u_df, xw)


def test_duplicate_pair_raises():
    u_df = pl.DataFrame({"COW": ["1"], "NAICSP": ["6111"]})
    xw = pl.DataFrame({"COW": ["1", "1"], "NAICSP": ["6111", "6111"], "bea_line": ["70", "51"]})
    with pytest.raises(ValueError, match=r"duplicate.*\(1, 6111\)"):
        apply_crosswalk(u_df, xw)


def test_committed_crosswalk_covers_universe():
    if not XW_PATH.exists():
        pytest.skip("no committed crosswalk")
    try:
        persons = u.load_persons(CFG)
    except FileNotFoundError:
        pytest.skip("PUMS data absent")
    # (COW, NAICSP) pairs don't depend on wages/CPI; filter directly like build_universe does.
    o, uc = CFG["orleans"], CFG["universe"]
    filtered = persons.filter(
        (pl.col("POWSP") == o["powsp"]) & pl.col("POWPUMA").is_in(o["powpuma"])
        & pl.col("COW").is_in(uc["cow_wage"]) & (pl.col("WAGP") > 0) & (pl.col("WKHP") > 0) & (pl.col("WKWN") > 0)
    )
    xw = pl.read_csv(XW_PATH, schema_overrides={"COW": pl.Utf8, "NAICSP": pl.Utf8, "bea_line": pl.Utf8})
    apply_crosswalk(filtered, xw)  # raises if anything is missing or duplicated


def test_industries_partition_total():
    try:
        bea = load_bea(CFG)
    except FileNotFoundError:
        pytest.skip("no live BEA data")
    industries = pl.read_csv(INDUSTRIES_PATH, schema_overrides={"line": pl.Utf8})
    cagdp2 = bea.filter((bea["table"] == "CAGDP2") & (bea["geo"] == CFG["bea"]["county_geo"]))
    total = cagdp2.filter(pl.col("line_code") == CFG["bea"]["gdp_total_line"]["line"])
    parts = cagdp2.filter(pl.col("line_code").is_in(industries["line"].to_list()))
    y0, y1 = CFG["years"]["pool"]
    for year in range(y0, y1 + 1):
        t = total.filter(pl.col("year") == year)
        p = parts.filter(pl.col("year") == year)
        if t["value"].null_count() or p["value"].null_count():
            pytest.fail(f"{year}: a suppressed (D) cell blocks the partition check")
        assert p["value"].sum() == pytest.approx(t["value"].item(), abs=5000)
