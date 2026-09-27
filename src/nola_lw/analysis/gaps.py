"""SPEC §5, §11.4-11.5: floor gap, the 12-cell household table, and replicate-weight SEs.
Ratios are computed inside each replicate."""
import polars as pl

from nola_lw.analysis.se import N_REPS, replicate_estimate
from nola_lw.fetch.mit import HOUSEHOLD_KEYS

SUMMARY_KEYS = ["workers", "below", "share_below", "total_gap", "mean_short_hr", "mean_short_yr"]


def _span_factor(years: list[int], pool: list[int]) -> float:
    return (pool[1] - pool[0] + 1) / (years[1] - years[0] + 1)


def _in_years(years: list[int]) -> pl.Expr:
    return pl.col("year").cast(pl.Int64).is_between(years[0], years[1])


def year_subset(df: pl.DataFrame, years: list[int], pool: list[int]) -> pl.DataFrame:
    """Filter to `years` [start, end] and rescale PWGTP/PWGTP1..80 by (pool span ÷ subset span)."""
    factor = _span_factor(years, pool)
    weight_cols = ["PWGTP"] + [f"PWGTP{i}" for i in range(1, N_REPS + 1)]
    return df.filter(_in_years(years)).with_columns([(pl.col(c) * factor) for c in weight_cols])


def add_floor_gap(u: pl.DataFrame, floor: float) -> pl.DataFrame:
    return u.with_columns(
        below=pl.col("wage_hr") < floor,
        gap_hr=(pl.lit(floor) - pl.col("wage_hr")).clip(lower_bound=0),
    ).with_columns(gap_yr=pl.col("gap_hr") * pl.col("hours"))


def add_own_gap(u: pl.DataFrame, thresholds: dict[str, float]) -> pl.DataFrame:
    """As add_floor_gap, but each worker against the living wage of their own household type (Q2)."""
    t = pl.col("household").replace_strict(thresholds)
    return u.with_columns(
        below=pl.col("wage_hr") < t,
        gap_hr=(t - pl.col("wage_hr")).clip(lower_bound=0),
    ).with_columns(gap_yr=pl.col("gap_hr") * pl.col("hours"))


def wsum(df: pl.DataFrame, w: str, col: str | None = None) -> float:
    return df[w].sum() if col is None else (df[col] * df[w]).sum()


def _safe_ratio(num: float, den: float) -> float:
    """0.0 rather than a ZeroDivisionError when a replicate's weighted denominator is 0
    (e.g. a group with no below-floor workers)."""
    return num / den if den else 0.0


_BELOW = pl.col("below")
STATS = {
    "workers": lambda d, w: wsum(d, w),
    "below": lambda d, w: wsum(d.filter(_BELOW), w),
    "share_below": lambda d, w: _safe_ratio(wsum(d.filter(_BELOW), w), wsum(d, w)),
    "total_gap": lambda d, w: wsum(d, w, "gap_yr"),
    "mean_short_hr": lambda d, w: _safe_ratio(wsum(d.filter(_BELOW), w, "gap_hr"), wsum(d.filter(_BELOW), w)),
    "mean_short_yr": lambda d, w: _safe_ratio(wsum(d.filter(_BELOW), w, "gap_yr"), wsum(d.filter(_BELOW), w)),
}
WINDOW_DIFF_KEYS = ["below", "share_below", "total_gap"]


def floor_summary(u: pl.DataFrame) -> dict[str, tuple[float | None, float | None]]:
    """Each `STATS` entry as (est, se). Mean shortfalls are (None, None) when nobody is below the floor."""
    out = {k: replicate_estimate(u, stat) for k, stat in STATS.items()}
    if not u["below"].any():
        out["mean_short_hr"] = out["mean_short_yr"] = (None, None)
    return out


def window_difference(g: pl.DataFrame, years: list[int], pool: list[int], z: float
                      ) -> dict[str, tuple[float, float, bool]]:
    """Paired pool − subset difference for `WINDOW_DIFF_KEYS`: d = stat(pool) − stat(subset rows,
    weights × pool/subset span), with the same replicate weight in both terms (the windows share
    data). `g` is the `add_floor_gap` pool frame. Returns (d, se(d), |d| > z·se(d))."""
    factor, insub = _span_factor(years, pool), _in_years(years)

    def paired(stat):
        return lambda d, w: stat(d, w) - stat(d.filter(insub).with_columns(pl.col(w) * factor), w)
    out = {}
    for k in WINDOW_DIFF_KEYS:
        d, se = replicate_estimate(g, paired(STATS[k]))
        out[k] = (d, se, abs(d) > z * se)
    return out


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


def _share_and_gap(g: pl.DataFrame) -> tuple[tuple[float, float], tuple[float, float]]:
    """(share_below, se), (total_gap, se) from an `add_floor_gap`-shaped, non-empty frame."""
    share_below = replicate_estimate(g, lambda d, w: _safe_ratio(wsum(d.filter(pl.col("below")), w), wsum(d, w)))
    total_gap = replicate_estimate(g, lambda d, w: wsum(d, w, "gap_yr"))
    return share_below, total_gap


def household_table(u_typed: pl.DataFrame, thresholds: dict[str, float], hours_full_time: int,
                     floor_type: str) -> pl.DataFrame:
    """12 rows in `HOUSEHOLD_KEYS` order: workers, share/gap below own threshold and the floor, annually and hourly.

    An empty cell reports `workers` = 0 but null shares/gaps (and their SEs) rather than 0.0, which would
    misleadingly read as "0% below"."""
    floor = thresholds[floor_type]
    null_stats = ["share_below_own", "gap_own", "share_below_floor", "annual_share_below", "annual_gap"]
    rows = []
    for key in HOUSEHOLD_KEYS:
        sub = u_typed.filter(pl.col("household") == key)
        if sub.height == 0:
            rows.append({"household": key, "workers": 0.0, "workers_se": 0.0}
                        | {f"{n}{suf}": None for n in null_stats for suf in ("", "_se")})
            continue
        own = thresholds[key]
        annual_own = own * hours_full_time
        workers = replicate_estimate(sub, lambda d, w: wsum(d, w))
        share_below_own, gap_own = _share_and_gap(add_floor_gap(sub, own))
        share_below_floor, _ = _share_and_gap(add_floor_gap(sub, floor))
        annual = sub.with_columns(annual_gap=(pl.lit(annual_own) - pl.col("earnings")).clip(lower_bound=0))
        annual_share = replicate_estimate(
            annual, lambda d, w: _safe_ratio(wsum(d.filter(pl.col("earnings") < annual_own), w), wsum(d, w)))
        annual_gap = replicate_estimate(annual, lambda d, w: wsum(d, w, "annual_gap"))
        rows.append({
            "household": key,
            "workers": workers[0], "workers_se": workers[1],
            "share_below_own": share_below_own[0], "share_below_own_se": share_below_own[1],
            "gap_own": gap_own[0], "gap_own_se": gap_own[1],
            "share_below_floor": share_below_floor[0], "share_below_floor_se": share_below_floor[1],
            "annual_share_below": annual_share[0], "annual_share_below_se": annual_share[1],
            "annual_gap": annual_gap[0], "annual_gap_se": annual_gap[1],
        })
    return pl.DataFrame(rows)
