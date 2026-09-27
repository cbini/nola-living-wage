"""SPEC §5, §11.4: floor gap and replicate-weight SEs. Ratios are computed inside each replicate."""
import polars as pl

from nola_lw.analysis.se import N_REPS, replicate_estimate

SUMMARY_KEYS = ["workers", "below", "share_below", "total_gap", "mean_short_hr", "mean_short_yr"]


def year_subset(df: pl.DataFrame, years: list[int], pool: list[int]) -> pl.DataFrame:
    """Filter to `years` [start, end] and rescale PWGTP/PWGTP1..80 by (pool span ÷ subset span)."""
    factor = (pool[1] - pool[0] + 1) / (years[1] - years[0] + 1)
    weight_cols = ["PWGTP"] + [f"PWGTP{i}" for i in range(1, N_REPS + 1)]
    return (df.filter(pl.col("year").cast(pl.Int64).is_between(years[0], years[1]))
              .with_columns([(pl.col(c) * factor) for c in weight_cols]))


def add_floor_gap(u: pl.DataFrame, floor: float) -> pl.DataFrame:
    return u.with_columns(
        below=pl.col("wage_hr") < floor,
        gap_hr=(pl.lit(floor) - pl.col("wage_hr")).clip(lower_bound=0),
    ).with_columns(gap_yr=pl.col("gap_hr") * pl.col("hours"))


def wsum(df: pl.DataFrame, w: str, col: str | None = None) -> float:
    return df[w].sum() if col is None else (df[col] * df[w]).sum()


def floor_summary(u: pl.DataFrame) -> dict[str, tuple[float, float]]:
    below = pl.col("below")
    return {
        "workers": replicate_estimate(u, lambda d, w: wsum(d, w)),
        "below": replicate_estimate(u, lambda d, w: wsum(d.filter(below), w)),
        "share_below": replicate_estimate(u, lambda d, w: wsum(d.filter(below), w) / wsum(d, w)),
        "total_gap": replicate_estimate(u, lambda d, w: wsum(d, w, "gap_yr")),
        "mean_short_hr": replicate_estimate(
            u, lambda d, w: wsum(d.filter(below), w, "gap_hr") / wsum(d.filter(below), w)),
        "mean_short_yr": replicate_estimate(
            u, lambda d, w: wsum(d.filter(below), w, "gap_yr") / wsum(d.filter(below), w)),
    }


def summary_by(u: pl.DataFrame, col: str) -> pl.DataFrame:
    rows = []
    for val in sorted(u[col].unique().to_list()):
        summary = floor_summary(u.filter(pl.col(col) == val))
        row = {col: val}
        for key, (est, se) in summary.items():
            row[key], row[f"{key}_se"] = est, se
        rows.append(row)
    return pl.DataFrame(rows)


def leakage(u: pl.DataFrame) -> pl.DataFrame:
    """Share of below-floor workers and of gap dollars, by residence, each with SE."""
    below = pl.col("below")
    rows = []
    for val in sorted(u["residence"].unique().to_list()):
        here = pl.col("residence") == val
        sw = replicate_estimate(u, lambda d, w, here=here: wsum(d.filter(below & here), w) / wsum(d.filter(below), w))
        sg = replicate_estimate(u, lambda d, w, here=here: wsum(d.filter(here), w, "gap_yr") / wsum(d, w, "gap_yr"))
        rows.append({"residence": val, "share_workers": sw[0], "share_workers_se": sw[1],
                     "share_gap": sg[0], "share_gap_se": sg[1]})
    return pl.DataFrame(rows)
