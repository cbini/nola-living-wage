"""SPEC §7, §12e: sensitivities — price pass-through, outliers, hours rule, residency, years,
metro thresholds. Every row but "outliers_included" drops flagged outliers from `u_typed`."""
from collections.abc import Callable

import polars as pl

from nola_lw.analysis.capacity import _cell
from nola_lw.analysis.gaps import add_floor_gap, add_own_gap, floor_summary, year_subset
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


def _row(sensitivity: str, variant: str, summary: dict, factor: float, loop_gain: float | None = None) -> dict:
    below_est, below_se = summary["below"]
    gap_est, gap_se = summary["total_gap"]
    return {"sensitivity": sensitivity, "variant": variant, "workers_below": below_est,
            "workers_below_se": below_se, "total_gap": gap_est, "total_gap_se": gap_se, "factor": factor,
            "loop_gain": loop_gain}


def passthrough_rows(sensitivity: str, gap_at: Callable[[float], pl.DataFrame], bases: dict[str, float],
                     ps: list[float], cfg) -> list[dict]:
    """One row per (p, base): the fixed point f = 1 + p * cost(f) / base, where `gap_at(f)` gives the
    universe with every threshold × f and cost is its gap × (1 + employer payroll tax rate).

    loop_gain is the slope of that map at the fixed point, p * cost'(f) / base: the share of each round's
    price rise that comes back in the next round (< 1 settles; >= 1 would not). The gap is piecewise linear
    in f, so cost'(f) is exact: each worker below adds weight × hours × threshold, and their threshold is
    (gap_hr + wage_hr) / f."""
    load = 1 + cfg["capacity"]["employer_payroll_tax_rate"]
    tol, max_iter = cfg["sensitivity"]["passthrough_tol"], cfg["sensitivity"]["passthrough_max_iter"]
    rows = []
    for p in ps:
        for name, base in bases.items():
            f = passthrough_factor(lambda f: floor_summary(gap_at(f))["total_gap"][0] * load, base, p, tol, max_iter)
            u = gap_at(f)
            slope = u.filter(pl.col("below")).select(
                (pl.col("PWGTP") * pl.col("hours") * (pl.col("gap_hr") + pl.col("wage_hr")) / f).sum()).item()
            rows.append(_row(sensitivity, f"p={p} base={name}", floor_summary(u), f, p * slope * load / base))
    return rows


def own_threshold_passthrough_rows(u: pl.DataFrame, cfg, bases: dict[str, float]) -> list[dict]:
    """Q2 price pass-through: every Orleans household threshold × f. `u` as in own_threshold_rows."""
    t = load_thresholds(cfg)
    return passthrough_rows("own_threshold_passthrough", lambda f: add_own_gap(u, {k: v * f for k, v in t.items()}),
                            bases, cfg["decisions"]["passthrough_p"], cfg)


def own_threshold_rows(u: pl.DataFrame, cfg) -> list[dict]:
    """Q2: workers below their own household's living wage, with Orleans (county) and metro thresholds.
    `u` is the headline universe (outliers dropped, pool window) with the `household` column."""
    return [_row("own_threshold", area, floor_summary(add_own_gap(u, load_thresholds(cfg, area=area))), 1.0)
            for area in ("county", "metro")]


def scaled_rows(u: pl.DataFrame, floor: float, cfg, wage_scale: dict[str, float]) -> list[dict]:
    """Survey pay raised by each factor (employer-reported total ÷ survey total) to test under-reporting.
    `u` is the headline universe (outliers dropped, pool window)."""
    return [_row("survey_scaled_to_bea", name,
                 floor_summary(add_floor_gap(u.with_columns(earnings=pl.col("earnings") * f,
                                                            wage_hr=pl.col("wage_hr") * f), floor)), 1.0)
            for name, f in wage_scale.items()]


def run_sensitivities(u_typed: pl.DataFrame, bea_ctx: dict, cfg, u_self: pl.DataFrame | None = None,
                      wage_scale: dict[str, float] | None = None) -> pl.DataFrame:
    """The sensitivity table (SPEC §7): headline, 3 pass-through p × 2 spending bases,
    outliers included, hours rule, Louisiana residents only, 2022-24 only, metro thresholds,
    and, when `u_self` (the universe built with `include_self_employed=True`) is given,
    self-employed included.

    `u_typed` is the built worker universe (with `outlier`, `residence`, `earnings`, `hours`,
    `wage_hr`, `year`, PWGTP*); `bea_ctx` = {"bea": <load_bea frame>, "cpi_json": <BLS CPI json>}.
    """
    pool, subset = cfg["years"]["pool"], cfg["years"]["subset"]
    floor_type, hours_full_time = cfg["mit"]["floor_type"], cfg["mit"]["hours_full_time"]

    floor = load_thresholds(cfg)[floor_type]
    headline_u = year_subset(u_typed.filter(~pl.col("outlier")), pool, pool)

    rows = [_row("headline", "headline", floor_summary(add_floor_gap(headline_u, floor)), 1.0)]

    years = list(range(pool[0], pool[1] + 1))
    bases = spending_bases(bea_ctx["bea"], bea_ctx["cpi_json"], cfg, years)
    rows += passthrough_rows("passthrough", lambda f: add_floor_gap(headline_u, floor * f), bases,
                             cfg["decisions"]["passthrough_p"], cfg)

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

    if u_self is not None:
        self_u = year_subset(u_self.filter(~pl.col("outlier")), pool, pool)
        rows.append(_row("self_employed_included", "self_employed_included",
                          floor_summary(add_floor_gap(self_u, floor)), 1.0))

    if "household" in headline_u.columns:
        rows += own_threshold_rows(headline_u, cfg)
        rows += own_threshold_passthrough_rows(headline_u, cfg, bases)

    if wage_scale:
        rows += scaled_rows(headline_u, floor, cfg, wage_scale)

    return pl.DataFrame(rows)
