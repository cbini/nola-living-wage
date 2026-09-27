"""SPEC §7, §12e: sensitivities — price pass-through, outliers, hours rule, residency, years,
metro thresholds. Every row but "outliers_included" drops flagged outliers from `u_typed`."""
from collections.abc import Callable

import polars as pl

from nola_lw.analysis.capacity import _cell
from nola_lw.analysis.gaps import add_floor_gap, floor_summary, year_subset
from nola_lw.build.households import load_thresholds
from nola_lw.fetch.bls import cpi_factor


def passthrough_factor(gap_at: Callable[[float], float], base: float, p: float, tol: float, max_iter: int) -> float:
    """Fixed-point solve for f = 1 + p * gap_at(f) / base (SPEC §7.1, D7). Raises RuntimeError if
    the relative change in f hasn't fallen below `tol` within `max_iter` iterations."""
    f = 1.0
    for _ in range(max_iter):
        new_f = 1 + p * gap_at(f) / base
        if abs(new_f - f) <= tol * abs(f):
            return new_f
        f = new_f
    raise RuntimeError(f"pass-through factor did not converge after {max_iter} iterations")


def add_hours_rule_gap(u: pl.DataFrame, floor: float, hours_full_time: int) -> pl.DataFrame:
    """SPEC §7.3 hours-rule variant: below = earnings < floor·hours_full_time (annual),
    gap = max(0, floor·hours_full_time − earnings), regardless of actual hours worked."""
    annual_floor = floor * hours_full_time
    return u.with_columns(
        below=pl.col("earnings") < annual_floor,
        gap_yr=(pl.lit(annual_floor) - pl.col("earnings")).clip(lower_bound=0),
    ).with_columns(gap_hr=pl.col("gap_yr") / pl.col("hours"))


def spending_bases(bea: pl.DataFrame, cpi_json: dict, cfg, years: list[int]) -> dict[str, float]:
    """The two price pass-through spending bases (SPEC §7.1, §12e), in target dollars, averaged
    over `years`. A suppressed cell in any year raises rather than silently dropping that year."""
    b, target = cfg["bea"], cfg["cpi"]["target"]
    pce_vals, gdp_vals = [], []
    for year in years:
        factor = cpi_factor(cpi_json, year, target)
        sapce = _cell(bea, "SAPCE1", "1", b["state_geo"], year)
        cainc = _cell(bea, "CAINC1", "1", b["county_geo"], year)
        sainc = _cell(bea, "SAINC1", "1", b["state_geo"], year)
        if sapce is None or cainc is None or sainc is None:
            raise ValueError(f"suppressed BEA cell for resident_pce spending base in {year}")
        pce_vals.append(sapce * factor * cainc / sainc)
        gdp = _cell(bea, "CAGDP2", "1", b["county_geo"], year)
        if gdp is None:
            raise ValueError(f"suppressed BEA cell for gdp spending base in {year}")
        gdp_vals.append(gdp * factor)
    return {"resident_pce": sum(pce_vals) / len(pce_vals), "gdp": sum(gdp_vals) / len(gdp_vals)}


def _row(sensitivity: str, variant: str, summary: dict, factor: float) -> dict:
    below_est, below_se = summary["below"]
    gap_est, gap_se = summary["total_gap"]
    return {"sensitivity": sensitivity, "variant": variant, "workers_below": below_est,
            "workers_below_se": below_se, "total_gap": gap_est, "total_gap_se": gap_se, "factor": factor}


def run_sensitivities(u_typed: pl.DataFrame, bea_ctx: dict, cfg) -> pl.DataFrame:
    """The 12-row sensitivity table (SPEC §7): headline, 3 pass-through p × 2 spending bases,
    outliers included, hours rule, Louisiana residents only, 2022-24 only, metro thresholds.

    `u_typed` is the built worker universe (with `outlier`, `residence`, `earnings`, `hours`,
    `wage_hr`, `year`, PWGTP*); `bea_ctx` = {"bea": <load_bea frame>, "cpi_json": <BLS CPI json>}.
    """
    pool, subset = cfg["years"]["pool"], cfg["years"]["subset"]
    floor_type, hours_full_time = cfg["mit"]["floor_type"], cfg["mit"]["hours_full_time"]
    sens = cfg["sensitivity"]

    floor = load_thresholds(cfg)[floor_type]
    headline_u = year_subset(u_typed.filter(~pl.col("outlier")), pool, pool)

    rows = [_row("headline", "headline", floor_summary(add_floor_gap(headline_u, floor)), 1.0)]

    years = list(range(pool[0], pool[1] + 1))
    bases = spending_bases(bea_ctx["bea"], bea_ctx["cpi_json"], cfg, years)
    for p in cfg["decisions"]["passthrough_p"]:
        for base_name, base_val in bases.items():
            def gap_at(f: float, floor: float = floor) -> float:
                return floor_summary(add_floor_gap(headline_u, floor * f))["total_gap"][0]
            factor = passthrough_factor(gap_at, base_val, p, sens["passthrough_tol"], sens["passthrough_max_iter"])
            summary = floor_summary(add_floor_gap(headline_u, floor * factor))
            rows.append(_row("passthrough", f"p={p} base={base_name}", summary, factor))

    outliers_u = year_subset(u_typed, pool, pool)
    rows.append(_row("outliers_included", "outliers_included",
                      floor_summary(add_floor_gap(outliers_u, floor)), 1.0))

    rows.append(_row("hours_rule", "hours_rule",
                      floor_summary(add_hours_rule_gap(headline_u, floor, hours_full_time)), 1.0))

    la_u = headline_u.filter(pl.col("residence").is_in(["orleans", "other_la"]))
    rows.append(_row("la_residents_only", "la_residents_only", floor_summary(add_floor_gap(la_u, floor)), 1.0))

    subset_u = year_subset(u_typed.filter(~pl.col("outlier")), subset, pool)
    rows.append(_row("years_2022_2024", "years_2022_2024", floor_summary(add_floor_gap(subset_u, floor)), 1.0))

    metro_floor = load_thresholds(cfg, area="metro")[floor_type]
    rows.append(_row("metro_thresholds", "metro_thresholds",
                      floor_summary(add_floor_gap(headline_u, metro_floor)), 1.0))

    return pl.DataFrame(rows)
