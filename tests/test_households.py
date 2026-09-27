import polars as pl

from nola_lw.build import households as h
from nola_lw.config import load_config

CFG = load_config()


def _persons(rows: list[dict]) -> pl.DataFrame:
    """Build a persons frame from a list of per-person dicts, defaulting missing fields."""
    defaults = {"SERIALNO": "2022HU0000001", "src": "la", "SFN": None, "SFR": None,
                "AGEP": 40, "WAGP": 30_000, "SEMP": 0}
    cols = {k: [] for k in ["SERIALNO", "SPORDER", "src", "RELSHIPP", "SFN", "SFR", "AGEP", "WAGP", "SEMP"]}
    for i, r in enumerate(rows):
        row = defaults | {"SPORDER": str(i + 1)} | r
        for k in cols:
            cols[k].append(row[k])
    return pl.DataFrame(cols, schema={"SERIALNO": pl.Utf8, "SPORDER": pl.Utf8, "src": pl.Utf8,
                                       "RELSHIPP": pl.Utf8, "SFN": pl.Utf8, "SFR": pl.Utf8,
                                       "AGEP": pl.Int64, "WAGP": pl.Int64, "SEMP": pl.Int64})


def _row(unit: pl.DataFrame, sporder: str) -> dict:
    return unit.filter(pl.col("SPORDER") == sporder).row(0, named=True)


def test_couple_both_working_two_kids():
    p = _persons([
        {"RELSHIPP": "20", "WAGP": 40_000},
        {"RELSHIPP": "21", "WAGP": 30_000},
        {"RELSHIPP": "25", "AGEP": 10, "WAGP": 0},
        {"RELSHIPP": "26", "AGEP": 8, "WAGP": 0},
    ])
    out = h.family_units(p, CFG)
    assert out["household"].unique().to_list() == ["a2_w2_c2"]


def test_subfamily_split():
    p = _persons([
        {"RELSHIPP": "20", "WAGP": 40_000},  # grandparent, reference
        {"RELSHIPP": "28", "SFN": "1", "SFR": "3", "WAGP": 20_000},  # daughter, parent of subfamily
        {"RELSHIPP": "28", "SFN": "1", "SFR": "5", "AGEP": 5, "WAGP": 0},  # grandson, child of subfamily
    ])
    out = h.family_units(p, CFG)
    assert _row(out, "1")["household"] == "a1_w1_c0"
    assert _row(out, "2")["household"] == "a1_w1_c1"
    assert _row(out, "3")["household"] == "a1_w1_c1"


def test_roommate_single():
    p = _persons([
        {"RELSHIPP": "20", "WAGP": 40_000},
        {"RELSHIPP": "34", "WAGP": 20_000},  # roommate
    ])
    out = h.family_units(p, CFG)
    assert _row(out, "1")["household"] == "a1_w1_c0"
    assert _row(out, "2")["household"] == "a1_w1_c0"
    assert out.filter(pl.col("SPORDER") == "1")["unit_id"][0] != out.filter(pl.col("SPORDER") == "2")["unit_id"][0]


def test_gq_single():
    p = _persons([
        {"SERIALNO": "2022GQ0000001", "RELSHIPP": "37", "WAGP": 20_000},
        {"SERIALNO": "2022GQ0000001", "RELSHIPP": "38", "WAGP": 0, "AGEP": 15},
    ])
    out = h.family_units(p, CFG)
    assert out["household"].to_list() == ["a1_w1_c0", "a1_w1_c0"]
    assert out["unit_id"][0] != out["unit_id"][1]


def test_adult_child_single():
    p = _persons([
        {"RELSHIPP": "20", "WAGP": 40_000},
        {"RELSHIPP": "26", "AGEP": 19, "WAGP": 10_000},  # own child, adult
    ])
    out = h.family_units(p, CFG)
    assert _row(out, "1")["household"] == "a1_w1_c0"
    assert _row(out, "2")["household"] == "a1_w1_c0"
    assert _row(out, "1")["unit_id"] != _row(out, "2")["unit_id"]


def test_four_kids_capped():
    p = _persons([
        {"RELSHIPP": "20", "WAGP": 40_000},
        *[{"RELSHIPP": "25", "AGEP": a, "WAGP": 0} for a in (2, 4, 6, 8)],
    ])
    out = h.family_units(p, CFG)
    ref = _row(out, "1")
    assert ref["household"] == "a1_w1_c3"
    assert ref["children_over_cap"] is True
    assert out.filter(pl.col("children_over_cap"))["household"].unique().to_list() == ["a1_w1_c3"]


def test_spouse_self_employed_counts_as_working():
    p = _persons([
        {"RELSHIPP": "20", "WAGP": 40_000},
        {"RELSHIPP": "21", "WAGP": 0, "SEMP": -500},
    ])
    out = h.family_units(p, CFG)
    assert out["household"].unique().to_list() == ["a2_w2_c0"]


def test_unattached_child_joins_reference_family():
    p = _persons([
        {"RELSHIPP": "20", "WAGP": 40_000},
        {"RELSHIPP": "30", "AGEP": 6, "WAGP": 0},  # grandchild, no subfamily, no parent present
    ])
    out = h.family_units(p, CFG)
    assert out["household"].unique().to_list() == ["a1_w1_c1"]
    assert _row(out, "1")["unit_id"] == _row(out, "2")["unit_id"]


def test_commuter_household_typed_from_parquet():
    p = _persons([
        {"src": "other", "RELSHIPP": "20", "WAGP": 40_000},
        {"src": "other", "RELSHIPP": "21", "WAGP": 30_000},
        {"src": "la", "RELSHIPP": "20", "WAGP": 5_000},  # unrelated LA household, same SERIALNO
    ])
    out = h.family_units(p, CFG)
    other = out.filter(pl.col("src") == "other")
    assert other["household"].unique().to_list() == ["a2_w2_c0"]
    la = out.filter(pl.col("src") == "la")
    assert la["household"].to_list() == ["a1_w1_c0"]

