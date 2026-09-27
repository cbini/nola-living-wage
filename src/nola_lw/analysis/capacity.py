"""SPEC §6, §11.6: county GOS model (upper and lower bound) and capacity ratios.

GOS (gross operating surplus) is not published for a county. It is modeled per industry line as
GDP - compensation - GDP * (state taxes-on-production-less-subsidies ratio) (the "upper bound": it
still includes depreciation and proprietors' income). The "lower bound" subtracts a modeled
consumption-of-fixed-capital (CFC) share of GDP, using the national CFC share by industry from the
BEA fixed-asset tables (D4). Government GOS is entirely CFC, so its lower bound is 0.
"""
import polars as pl

from nola_lw.analysis.gaps import floor_summary, summary_by
from nola_lw.fetch.bls import cpi_factor

MONEY_COLS = ["gdp", "comp", "gos", "gos_low", "wages"]
GOV_LINE = "83"  # CAGDP2/CAINC6N/SAGDP2 "Government and government enterprises" (crosswalk.gov_line)


def gos(gdp: float | None, comp: float | None, tax_ratio: float | None) -> float | None:
    """GDP - compensation - GDP * (net taxes on production ratio). Null if any input is null (suppressed)."""
    if gdp is None or comp is None or tax_ratio is None:
        return None
    return gdp - comp - gdp * tax_ratio


def validate_gos_method(bea: pl.DataFrame, cfg) -> float:
    """Max |SAGDP2 - SAGDP4 - SAGDP3 - SAGDP7| (Louisiana), over every line common to all four
    tables and the pool years. Raises if it exceeds `capacity.gos_validation_tol_usd`."""
    b = cfg["bea"]
    y0, y1 = cfg["years"]["pool"]
    tables = ["SAGDP2", "SAGDP3", "SAGDP4", "SAGDP7"]
    frames = {t: bea.filter((pl.col("table") == t) & (pl.col("geo") == b["state_geo"])
                            & pl.col("year").is_between(y0, y1)).select("line_code", "year", "value")
              for t in tables}
    joined = frames["SAGDP2"].rename({"value": "SAGDP2"})
    for t in tables[1:]:
        joined = joined.join(frames[t].rename({"value": t}), on=["line_code", "year"])
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
    county, state, national = b["county_geo"], b["state_geo"], b["national_geo"]
    wl = b["wages_line"]
    y0, y1 = cfg["years"]["pool"]
    ind = [(r["line"], r["cainc6n_lines"].split(), r["fa_line"] or None)
           for r in industries.select("line", "cainc6n_lines", "fa_line").to_dicts()]

    rows = []
    for year in range(y0, y1 + 1):
        line_terms, gov_gos = [], None  # (gdp * cfc_share) per non-government line, for total/private
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
            if line == GOV_LINE:
                gos_low, gov_gos = 0.0, g
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
        t_gos_low = None if t_gos is None or terms_sum is None or gov_gos is None else t_gos - terms_sum - gov_gos
        t_wages = _cell(bea, wl["table"], wl["line"], county, year)
        rows.append({"line": "total", "year": year, "gdp": t_gdp, "comp": t_comp, "tax_ratio": t_tax,
                    "cfc_share": None, "gos": t_gos, "gos_low": t_gos_low, "wages": t_wages})

        p_gdp = _cell(bea, "CAGDP2", cap["private_line"], county, year)
        p_comp = _sum_cells(bea, "CAINC6N", cap["cainc6n_private"], county, year)
        p_tax = _tax_ratio(bea, cap["private_line"], state, year)
        p_gos = gos(p_gdp, p_comp, p_tax)
        p_gos_low = None if p_gos is None or terms_sum is None else p_gos - terms_sum
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


def gap_by_line(u: pl.DataFrame) -> pl.DataFrame:
    """Per-line gap (± SE) for `capacity_table`: `summary_by(u, "bea_line")`, plus "total" (all
    workers) and "private" (cow_class in private, nonprofit)."""
    by_line = summary_by(u, "bea_line").select(line="bea_line", gap="total_gap", gap_se="total_gap_se")
    total = floor_summary(u)["total_gap"]
    private = floor_summary(u.filter(pl.col("cow_class").is_in(["private", "nonprofit"])))["total_gap"]
    extra = pl.DataFrame({"line": ["total", "private"], "gap": [total[0], private[0]],
                          "gap_se": [total[1], private[1]]})
    return pl.concat([by_line, extra])


def capacity_table(gap_by_line: pl.DataFrame, panel_mean: pl.DataFrame) -> pl.DataFrame:
    """One row per line: gap, gap_se, gdp, comp, gos, gos_low, gap_gdp/comp/gos/gos_low/wages, and
    self_funding / self_funding_low in {"pass", "fail", "suppressed", "n/a" (line 83)}."""
    df = panel_mean.join(gap_by_line, on="line", how="left")
    df = df.with_columns(
        gap_gdp=pl.col("gap") / pl.col("gdp"), gap_comp=pl.col("gap") / pl.col("comp"),
        gap_gos=pl.col("gap") / pl.col("gos"), gap_gos_low=pl.col("gap") / pl.col("gos_low"),
        gap_wages=pl.col("gap") / pl.col("wages"),
    )
    def _status(gos_col: str) -> pl.Expr:
        return (pl.when(pl.col("line") == GOV_LINE).then(pl.lit("n/a"))
                  .when(pl.col(gos_col).is_null()).then(pl.lit("suppressed"))
                  .when(pl.col("gap") <= pl.col(gos_col)).then(pl.lit("pass"))
                  .otherwise(pl.lit("fail")))
    return df.with_columns(self_funding=_status("gos"), self_funding_low=_status("gos_low"))


def gos_tests(u: pl.DataFrame, panel_mean: pl.DataFrame) -> dict[str, tuple[float, float]]:
    """(a) private+nonprofit gap / private GOS (upper, lower); (b) all-sector gap / total GOS
    (upper, lower); government gap / government (line 83) compensation."""
    def denom(line: str, col: str) -> float:
        return panel_mean.filter(pl.col("line") == line)[col][0]

    def scale(est_se: tuple[float, float], d: float) -> tuple[float, float]:
        est, se = est_se
        return est / d, se / d

    private_gap = floor_summary(u.filter(pl.col("cow_class").is_in(["private", "nonprofit"])))["total_gap"]
    total_gap = floor_summary(u)["total_gap"]
    gov_gap = floor_summary(u.filter(pl.col("bea_line") == GOV_LINE))["total_gap"]

    return {
        "private_upper": scale(private_gap, denom("private", "gos")),
        "private_lower": scale(private_gap, denom("private", "gos_low")),
        "total_upper": scale(total_gap, denom("total", "gos")),
        "total_lower": scale(total_gap, denom("total", "gos_low")),
        "government": scale(gov_gap, denom(GOV_LINE, "comp")),
    }
