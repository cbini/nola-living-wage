"""SPEC §6, §11.6: county GOS model (upper and lower bound) and capacity ratios.

GOS (gross operating surplus) is not published for a county. It is modeled per industry line as
GDP - compensation - GDP * (state taxes-on-production-less-subsidies ratio) (the "upper bound": it
still includes depreciation and proprietors' income). The "lower bound" subtracts a modeled
consumption-of-fixed-capital (CFC) share of GDP, using the national CFC share by industry from the
BEA fixed-asset tables (D4). Government GOS is entirely CFC, so its lower bound is 0.
"""
from pathlib import Path

import polars as pl

from nola_lw.analysis.gaps import floor_summary, summary_by
from nola_lw.fetch.bls import cpi_factor

MONEY_COLS = ["gdp", "comp", "gos", "gos_low", "wages"]
INDUSTRIES_PATH = Path("crosswalks/bea_industries.csv")


def _private_classes(cfg) -> list[str]:
    """cow_class labels that are not "public" (config.universe.cow_class), e.g. private, nonprofit."""
    return sorted(set(cfg["universe"]["cow_class"].values()) - {"public"})


def gos(gdp: float | None, comp: float | None, tax_ratio: float | None) -> float | None:
    """GDP - compensation - GDP * (net taxes on production ratio). Null if any input is null (suppressed)."""
    if gdp is None or comp is None or tax_ratio is None:
        return None
    return gdp - comp - gdp * tax_ratio


def validate_gos_method(bea: pl.DataFrame, cfg, industries_path: Path = INDUSTRIES_PATH) -> float:
    """Max |SAGDP2 - SAGDP4 - SAGDP3 - SAGDP7| (Louisiana), over the 20 `industries_path` lines,
    line 1, and the pool years. Raises if any of those cells is flagged (the identity can't be
    validated against a suppressed value) or if the residual exceeds `capacity.gos_validation_tol_usd`."""
    b = cfg["bea"]
    y0, y1 = cfg["years"]["pool"]
    lines = ["1"] + pl.read_csv(industries_path, infer_schema_length=0)["line"].to_list()
    tables = ["SAGDP2", "SAGDP3", "SAGDP4", "SAGDP7"]
    frames = {t: bea.filter((pl.col("table") == t) & (pl.col("geo") == b["state_geo"])
                            & pl.col("year").is_between(y0, y1) & pl.col("line_code").is_in(lines))
                    .select("line_code", "year", "value", "flag")
              for t in tables}
    joined = frames["SAGDP2"].rename({"value": "SAGDP2", "flag": "flag_SAGDP2"})
    for t in tables[1:]:
        joined = joined.join(frames[t].rename({"value": t, "flag": f"flag_{t}"}), on=["line_code", "year"])
    flag_cols = ["flag_SAGDP2"] + [f"flag_{t}" for t in tables[1:]]
    flagged = joined.filter(pl.any_horizontal([pl.col(c).is_not_null() for c in flag_cols]))
    if flagged.height:
        cells = ", ".join(f"line {r['line_code']} {r['year']}" for r in flagged.iter_rows(named=True))
        raise ValueError(f"cannot validate GOS method: suppressed cell(s) at {cells}")
    resid = (joined["SAGDP2"] - joined["SAGDP4"] - joined["SAGDP3"] - joined["SAGDP7"]).abs()
    max_resid = float(resid.max())
    tol = cfg["capacity"]["gos_validation_tol_usd"]
    if max_resid > tol:
        raise ValueError(f"GOS identity residual ${max_resid:,.0f} exceeds tolerance ${tol:,.0f}")
    return max_resid


def _cell(df: pl.DataFrame, table: str, line: str, geo: str, year: int) -> float | None:
    row = df.filter((pl.col("table") == table) & (pl.col("line_code") == line)
                    & (pl.col("geo") == geo) & (pl.col("year") == year))
    if row.height != 1:
        raise ValueError(f"expected exactly one {table} line {line} geo {geo} year {year} row, got {row.height}")
    r = row.row(0, named=True)
    return None if r["flag"] is not None else r["value"]


def _sum_cells(df: pl.DataFrame, table: str, lines: list[str], geo: str, year: int) -> float | None:
    vals = [_cell(df, table, line, geo, year) for line in lines]
    return None if any(v is None for v in vals) else sum(vals)


def _tax_ratio(bea: pl.DataFrame, line: str, state_geo: str, year: int) -> float | None:
    g = _cell(bea, "SAGDP2", line, state_geo, year)
    t = _cell(bea, "SAGDP3", line, state_geo, year)
    return None if g is None or t is None else t / g


def _fa_cell(fa: pl.DataFrame, line: str, year: int) -> float | None:
    row = fa.filter((pl.col("line_code") == line) & (pl.col("year") == year))
    if row.height != 1:
        raise ValueError(f"expected exactly one FA line {line} year {year} row, got {row.height}")
    r = row.row(0, named=True)
    return None if r["flag"] is not None else r["value"]


def bea_panel(bea: pl.DataFrame, fa: pl.DataFrame, industries: pl.DataFrame, cfg) -> pl.DataFrame:
    """One row per (line, year): the 20 `industries` lines plus "total" (all workers) and "private"
    (cow_class in private, nonprofit). `wages` (CAINC5N line 50) is filled only for "total"."""
    b, cap = cfg["bea"], cfg["capacity"]
    gov_line = cfg["crosswalk"]["gov_line"]
    county, state, national = b["county_geo"], b["state_geo"], b["national_geo"]
    wl = b["wages_line"]
    y0, y1 = cfg["years"]["pool"]
    ind = [(r["line"], r["cainc6n_lines"].split(), r["fa_line"] or None)
           for r in industries.select("line", "cainc6n_lines", "fa_line").to_dicts()]

    rows = []
    for year in range(y0, y1 + 1):
        line_terms, gov_low = [], None  # (gdp * cfc_share) per non-government line, for private
        for line, cainc6n_lines, fa_line in ind:
            gdp = _cell(bea, "CAGDP2", line, county, year)
            comp = _sum_cells(bea, "CAINC6N", cainc6n_lines, county, year)
            tax_ratio = _tax_ratio(bea, line, state, year)
            g = gos(gdp, comp, tax_ratio)
            if fa_line is None:
                cfc_share = None
            else:
                fa_val = _fa_cell(fa, fa_line, year)
                nat_gdp = _cell(bea, "SAGDP2", line, national, year)
                cfc_share = None if fa_val is None or nat_gdp is None else fa_val / nat_gdp
            term = None if gdp is None or cfc_share is None else gdp * cfc_share
            if line == gov_line:
                gos_low = gov_low = 0.0
            else:
                gos_low = None if g is None or term is None else g - term
                line_terms.append(term)
            rows.append({"line": line, "year": year, "gdp": gdp, "comp": comp, "tax_ratio": tax_ratio,
                        "cfc_share": cfc_share, "gos": g, "gos_low": gos_low, "wages": None})

        terms_sum = None if any(t is None for t in line_terms) else sum(line_terms)

        t_gdp = _cell(bea, "CAGDP2", cap["total_line"], county, year)
        t_comp = _sum_cells(bea, "CAINC6N", cap["cainc6n_total"], county, year)
        t_tax = _tax_ratio(bea, cap["total_line"], state, year)
        t_gos = gos(t_gdp, t_comp, t_tax)
        t_wages = _cell(bea, wl["table"], wl["line"], county, year)

        p_gdp = _cell(bea, "CAGDP2", cap["private_line"], county, year)
        p_comp = _sum_cells(bea, "CAINC6N", cap["cainc6n_private"], county, year)
        p_tax = _tax_ratio(bea, cap["private_line"], state, year)
        p_gos = gos(p_gdp, p_comp, p_tax)
        p_gos_low = None if p_gos is None or terms_sum is None else p_gos - terms_sum
        # total lower bound = private lower bound + government lower bound, so it can't undercut private
        # (total GOS less CFC would, because total and private use different aggregate tax ratios)
        t_gos_low = None if p_gos_low is None or gov_low is None else p_gos_low + gov_low
        rows.append({"line": "total", "year": year, "gdp": t_gdp, "comp": t_comp, "tax_ratio": t_tax,
                    "cfc_share": None, "gos": t_gos, "gos_low": t_gos_low, "wages": t_wages})
        rows.append({"line": "private", "year": year, "gdp": p_gdp, "comp": p_comp, "tax_ratio": p_tax,
                    "cfc_share": None, "gos": p_gos, "gos_low": p_gos_low, "wages": None})

    schema = {"line": pl.Utf8, "year": pl.Int64, "gdp": pl.Float64, "comp": pl.Float64, "tax_ratio": pl.Float64,
              "cfc_share": pl.Float64, "gos": pl.Float64, "gos_low": pl.Float64, "wages": pl.Float64}
    return pl.DataFrame(rows, schema=schema)


def to_target_dollars(panel: pl.DataFrame, cpi_json: dict, cfg) -> pl.DataFrame:
    """Scale every money column per year: value_y * CPI(target) / CPI annual mean(y)."""
    target = cfg["cpi"]["target"]
    money_cols = [c for c in MONEY_COLS if c in panel.columns]
    out = panel.with_columns(
        _factor=pl.col("year").map_elements(lambda y: cpi_factor(cpi_json, y, target), return_dtype=pl.Float64))
    out = out.with_columns([(pl.col(c) * pl.col("_factor")).alias(c) for c in money_cols])
    return out.drop("_factor")


def window_mean(panel: pl.DataFrame, years: list[int]) -> pl.DataFrame:
    """Mean by line over `years`; a column is null for a line if any of those years is null."""
    cols = [c for c in panel.columns if c not in ("line", "year")]
    df = panel.filter(pl.col("year").is_in(years))
    exprs = [pl.when(pl.col(c).is_null().any()).then(None).otherwise(pl.col(c).mean()).alias(c) for c in cols]
    return df.group_by("line", maintain_order=True).agg(exprs)


def gap_by_line(u: pl.DataFrame, cfg) -> pl.DataFrame:
    """Per-line gap (± SE) for `capacity_table`: `summary_by(u, "bea_line")`, plus "total" (all
    workers) and "private" (cow_class in private, nonprofit, per config.universe.cow_class)."""
    by_line = summary_by(u, "bea_line").select(line="bea_line", gap="total_gap", gap_se="total_gap_se")
    total = floor_summary(u)["total_gap"]
    private = floor_summary(u.filter(pl.col("cow_class").is_in(_private_classes(cfg))))["total_gap"]
    extra = pl.DataFrame({"line": ["total", "private"], "gap": [total[0], private[0]],
                          "gap_se": [total[1], private[1]]})
    return pl.concat([by_line, extra])


def capacity_table(gap_by_line: pl.DataFrame, panel_mean: pl.DataFrame, gov_line: str,
                   load: float = 0.0) -> pl.DataFrame:
    """One row per line: gap, gap_se, cost (= gap * (1 + `load`), the employer's cost including its
    payroll taxes, `capacity.employer_payroll_tax_rate`), gdp, comp, gos, gos_low,
    gap_gdp/comp/gos/gos_low (cost / denominator, since compensation and GOS both include employer
    payroll taxes) and gap_wages (gap / wages, since wages exclude them), each with its own _se;
    null, not inf or sign-inverted, when the denominator is <= 0. self_funding / self_funding_low
    in {"pass", "fail", "suppressed", "no sample", "n/a" (`gov_line`)} compare cost with GOS.
    "no sample" means no PUMS-observed gap for that line (a null after the join), distinct from
    "suppressed" (a null GOS from a flagged BEA cell)."""
    df = panel_mean.join(gap_by_line, on="line", how="left").with_columns(
        cost=pl.col("gap") * (1 + load), cost_se=pl.col("gap_se") * (1 + load))

    def ratio(num: str, denom_col: str) -> pl.Expr:
        valid = pl.col(denom_col) > 0
        return pl.when(valid).then(pl.col(num) / pl.col(denom_col)).otherwise(None)

    df = df.with_columns(
        gap_gdp=ratio("cost", "gdp"), gap_gdp_se=ratio("cost_se", "gdp"),
        gap_comp=ratio("cost", "comp"), gap_comp_se=ratio("cost_se", "comp"),
        gap_gos=ratio("cost", "gos"), gap_gos_se=ratio("cost_se", "gos"),
        gap_gos_low=ratio("cost", "gos_low"), gap_gos_low_se=ratio("cost_se", "gos_low"),
        gap_wages=ratio("gap", "wages"), gap_wages_se=ratio("gap_se", "wages"),
    )

    def _status(gos_col: str) -> pl.Expr:
        return (pl.when(pl.col("line") == gov_line).then(pl.lit("n/a"))
                  .when(pl.col("gap").is_null()).then(pl.lit("no sample"))
                  .when(pl.col(gos_col).is_null()).then(pl.lit("suppressed"))
                  .when(pl.col("gap") == 0).then(pl.lit("pass"))  # nothing to fund, whatever the GOS
                  .when(pl.col("cost") <= pl.col(gos_col)).then(pl.lit("pass"))
                  .otherwise(pl.lit("fail")))
    return df.with_columns(self_funding=_status("gos"), self_funding_low=_status("gos_low"))


def gos_tests(u: pl.DataFrame, panel_mean: pl.DataFrame, cfg) -> dict[str, tuple[float | None, float | None]]:
    """(a) private+nonprofit gap / private GOS (upper, lower); (b) all-sector gap / total GOS
    (upper, lower); government gap / government (`crosswalk.gov_line`) compensation; and "*_ex" for
    (a), (b) with the `capacity.imputed_rent_line` (real estate, whose GOS includes imputed rent on
    owner-occupied housing) removed from both gap and GOS. Each ratio is null (not inf or
    sign-inverted) when its denominator is null or <= 0. Each numerator is the employer's cost, the
    gap * (1 + `capacity.employer_payroll_tax_rate`)."""
    gov_line, rent_line = cfg["crosswalk"]["gov_line"], cfg["capacity"]["imputed_rent_line"]
    load = 1 + cfg["capacity"]["employer_payroll_tax_rate"]

    def denom(line: str, col: str, ex: bool = False) -> float | None:
        d = panel_mean.filter(pl.col("line") == line)[col][0]
        if not ex:
            return d
        r = panel_mean.filter(pl.col("line") == rent_line)[col][0]
        return None if d is None or r is None else d - r

    def scale(est_se: tuple[float, float], d: float) -> tuple[float | None, float | None]:
        if d is None or d <= 0:
            return None, None
        est, se = est_se
        return est * load / d, se * load / d

    private_gap = floor_summary(u.filter(pl.col("cow_class").is_in(_private_classes(cfg))))["total_gap"]
    total_gap = floor_summary(u)["total_gap"]
    gov_gap = floor_summary(u.filter(pl.col("bea_line") == gov_line))["total_gap"]
    u_ex = u.filter(pl.col("bea_line") != rent_line)
    private_gap_ex = floor_summary(u_ex.filter(pl.col("cow_class").is_in(_private_classes(cfg))))["total_gap"]
    total_gap_ex = floor_summary(u_ex)["total_gap"]

    return {
        "private_upper": scale(private_gap, denom("private", "gos")),
        "private_lower": scale(private_gap, denom("private", "gos_low")),
        "total_upper": scale(total_gap, denom("total", "gos")),
        "total_lower": scale(total_gap, denom("total", "gos_low")),
        "government": scale(gov_gap, denom(gov_line, "comp")),
        "private_upper_ex": scale(private_gap_ex, denom("private", "gos", ex=True)),
        "private_lower_ex": scale(private_gap_ex, denom("private", "gos_low", ex=True)),
        "total_upper_ex": scale(total_gap_ex, denom("total", "gos", ex=True)),
        "total_lower_ex": scale(total_gap_ex, denom("total", "gos_low", ex=True)),
    }
