import polars as pl
import pytest

from nola_lw.analysis import gaps


def _weighted(n, pwgtp):
    """n rows, PWGTP given, replicate weights equal to PWGTP (SE = 0)."""
    return {"PWGTP": pwgtp} | {f"PWGTP{i}": pwgtp for i in range(1, 81)}


def test_year_subset_scales_replicates():
    df = pl.DataFrame({"year": [2020, 2021, 2022, 2023, 2024]} | _weighted(5, [1] * 5))
    out = gaps.year_subset(df, [2022, 2024], [2020, 2024])
    assert out.height == 3
    assert out["PWGTP"].to_list() == pytest.approx([5 / 3] * 3)
    assert out["PWGTP80"].to_list() == pytest.approx([5 / 3] * 3)


def test_gap_math():
    df = pl.DataFrame({"wage_hr": [15.0, 25.0, 20.0], "hours": [2000.0, 2000.0, 2000.0]})
    out = gaps.add_floor_gap(df, 20.0)
    assert out["below"].to_list() == [True, False, False]
    assert out["gap_hr"].to_list() == pytest.approx([5.0, 0.0, 0.0])
    assert out["gap_yr"].to_list() == pytest.approx([10_000.0, 0.0, 0.0])


def test_floor_summary_hand_computed():
    df = pl.DataFrame({"wage_hr": [15.0, 25.0], "hours": [2000.0, 2000.0]} | _weighted(2, [3, 1]))
    u = gaps.add_floor_gap(df, 20.0)
    s = gaps.floor_summary(u)
    assert s["workers"][0] == pytest.approx(4)
    assert s["below"][0] == pytest.approx(3)
    assert s["share_below"][0] == pytest.approx(0.75)
    assert s["total_gap"][0] == pytest.approx(30_000)
    assert s["mean_short_hr"][0] == pytest.approx(5.0)
    assert s["mean_short_yr"][0] == pytest.approx(10_000.0)


def test_leakage_shares_sum_to_one():
    df = pl.DataFrame({
        "wage_hr": [15.0, 18.0, 25.0],
        "hours": [2000.0, 2000.0, 2000.0],
        "residence": ["orleans", "other_la", "out_of_state"],
    } | _weighted(3, [3, 2, 1]))
    u = gaps.add_floor_gap(df, 20.0)
    lk = gaps.leakage(u)
    assert lk["share_workers"].sum() == pytest.approx(1.0)
    assert lk["share_gap"].sum() == pytest.approx(1.0)
