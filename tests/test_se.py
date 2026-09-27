import polars as pl
import pytest

from nola_lw.analysis.se import moe90, replicate_estimate, replicate_se, weighted_total


def test_se_formula():
    assert replicate_se(100, [101] * 40 + [99] * 40) == pytest.approx(2.0)


def test_se_requires_80():
    with pytest.raises(ValueError):
        replicate_se(100, [100] * 79)


def test_moe90():
    assert moe90(2.0, 1.645) == pytest.approx(3.29)


def test_weighted_total_adjinc():
    df = pl.DataFrame({"WAGP": [10_000, 20_000], "ADJINC": [1_050_000, 1_050_000], "PWGTP": [3, 5]}
                      | {f"PWGTP{i}": [4, 5] for i in range(1, 81)})
    df = df.with_columns(v=pl.col("WAGP") * pl.col("ADJINC") / 1e6)
    est, se = weighted_total(df, "v")
    assert est == pytest.approx((3 * 10_000 + 5 * 20_000) * 1.05)
    rep = (4 * 10_000 + 5 * 20_000) * 1.05
    assert se == pytest.approx((4 / 80 * 80 * (rep - est) ** 2) ** 0.5)


def test_ratio_se():
    # full mean = 0.5; every replicate weighting shifts the mean by exactly ±0.5 -> SE 1.0
    df = pl.DataFrame({"x": [0.0, 1.0], "PWGTP": [1, 1]}
                      | {f"PWGTP{i}": [1, 0] if i % 2 else [0, 1] for i in range(1, 81)})

    def mean(d, w):
        return (d["x"] * d[w]).sum() / d[w].sum()

    est, se = replicate_estimate(df, mean)
    assert est == pytest.approx(0.5)
    assert se == pytest.approx(1.0)
