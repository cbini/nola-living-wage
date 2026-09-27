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


def test_floor_summary_no_one_below_floor():
    df = pl.DataFrame({"wage_hr": [25.0, 30.0], "hours": [2000.0, 2000.0]} | _weighted(2, [3, 1]))
    u = gaps.add_floor_gap(df, 20.0)
    s = gaps.floor_summary(u)
    assert s["below"][0] == pytest.approx(0.0)
    for k in ("mean_short_hr", "mean_short_yr"):
        assert s[k] == (None, None)  # undefined, not $0


def test_household_table_has_12_rows_in_order():
    thresholds = {k: 10.0 + i for i, k in enumerate(gaps.HOUSEHOLD_KEYS)}
    u = pl.DataFrame({
        "household": ["a1_w1_c0", "a2_w2_c1"],
        "wage_hr": [8.0, 30.0],
        "hours": [2000.0, 2000.0],
        "earnings": [16_000.0, 60_000.0],
        "PWGTP": [10, 20],
    } | {f"PWGTP{i}": [10, 20] for i in range(1, 81)})
    out = gaps.household_table(u, thresholds, hours_full_time=2000, floor_type="a1_w1_c0")
    assert out["household"].to_list() == gaps.HOUSEHOLD_KEYS
    row0 = out.filter(pl.col("household") == "a1_w1_c0").row(0, named=True)
    assert row0["workers"] == pytest.approx(10)
    assert row0["share_below_own"] == pytest.approx(1.0)
    assert row0["gap_own"] == pytest.approx((10.0 - 8.0) * 2000 * 10)
    assert row0["annual_share_below"] == pytest.approx(1.0)
    assert row0["annual_gap"] == pytest.approx((10.0 * 2000 - 16_000.0) * 10)
    other_row = out.filter(pl.col("household") == "a2_w1_c0").row(0, named=True)
    assert other_row["workers"] == pytest.approx(0)


def test_household_table_empty_cell_is_null_not_zero():
    thresholds = {k: 10.0 + i for i, k in enumerate(gaps.HOUSEHOLD_KEYS)}
    u = pl.DataFrame({
        "household": ["a1_w1_c0"],
        "wage_hr": [8.0],
        "hours": [2000.0],
        "earnings": [16_000.0],
        "PWGTP": [10],
    } | {f"PWGTP{i}": [10] for i in range(1, 81)})
    out = gaps.household_table(u, thresholds, hours_full_time=2000, floor_type="a1_w1_c0")
    empty = out.filter(pl.col("household") == "a2_w2_c3").row(0, named=True)
    assert empty["workers"] == pytest.approx(0)
    for col in ["share_below_own", "gap_own", "share_below_floor", "annual_share_below", "annual_gap"]:
        assert empty[col] is None
        assert empty[f"{col}_se"] is None


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


def _two_windows(rep_noise: float) -> pl.DataFrame:
    """Five years, one row each; 2020-21 workers are below a $20 floor, 2022-24 are not.
    Replicate weights swing ±rep_noise around PWGTP, alternating by replicate, early rows against late rows."""
    rows = {"year": [str(y) for y in range(2020, 2025)], "wage_hr": [10.0, 10.0, 30.0, 30.0, 30.0],
            "hours": [2000.0] * 5, "PWGTP": [10.0] * 5}
    rows |= {f"PWGTP{r}": [10.0 * (1 + rep_noise * (-1) ** (r + (i >= 2))) for i in range(5)] for r in range(1, 81)}
    return gaps.add_floor_gap(pl.DataFrame(rows), 20.0)


def test_window_difference_paired_significant():
    out = gaps.window_difference(_two_windows(0.01), [2022, 2024], [2020, 2024], z=1.645)
    d, se, differs = out["below"]
    assert d == pytest.approx(20.0)  # pool 20 below; subset 0 below
    assert se > 0 and differs
    assert out["share_below"][0] == pytest.approx(0.4) and out["share_below"][2]
    assert out["total_gap"][0] == pytest.approx(20 * 10 * 2000) and out["total_gap"][2]


def test_window_difference_paired_not_significant():
    out = gaps.window_difference(_two_windows(0.9), [2022, 2024], [2020, 2024], z=1.645)
    for k in ("below", "share_below", "total_gap"):
        d, se, differs = out[k]
        assert abs(d) <= 1.645 * se and not differs


def test_add_own_gap_uses_each_workers_household_threshold():
    u = pl.DataFrame({"household": ["a1_w1_c0", "a1_w1_c1"], "wage_hr": [18.0, 18.0], "hours": [1000.0, 1000.0]})
    out = gaps.add_own_gap(u, {"a1_w1_c0": 20.0, "a1_w1_c1": 30.0})
    assert out["below"].to_list() == [True, True]
    assert out["gap_yr"].to_list() == [2000.0, 12000.0]
