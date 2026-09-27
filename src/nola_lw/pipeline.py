"""SPEC §11.7: load → universe → floor gap → households → crosswalk → capacity → sensitivities → report."""
import json
from pathlib import Path

import polars as pl

from nola_lw.analysis import capacity as cap
from nola_lw.analysis.gaps import (add_floor_gap, floor_summary, household_table, leakage, summary_by,
                                   window_difference, year_subset)
from nola_lw.analysis.se import weighted_total
from nola_lw.analysis.sensitivity import run_sensitivities
from nola_lw.build.crosswalk import apply_crosswalk
from nola_lw.build.households import family_units, load_thresholds
from nola_lw.build.universe import build_universe, load_persons, self_employed_count
from nola_lw.checkpoint import bea_wages_2024usd, wage_check
from nola_lw.fetch.bea import load_bea
from nola_lw.fetch.bea_api import load_fixed_assets
from nola_lw.report.results import write_results

CROSSWALK_PATH = Path("crosswalks/cow_naicsp_to_bea.csv")
UNIT_KEYS = ["src", "SERIALNO", "SPORDER"]


def _weighted_count(df: pl.DataFrame) -> tuple[float, float]:
    return weighted_total(df.with_columns(one=pl.lit(1.0)), "one")


def _window(u: pl.DataFrame, panel: pl.DataFrame, thresholds: dict, years: list[int], cfg) -> dict:
    pool, floor_type = cfg["years"]["pool"], cfg["mit"]["floor_type"]
    sub = year_subset(u, years, pool)
    g = add_floor_gap(sub, thresholds[floor_type])
    pm = cap.window_mean(panel, list(range(years[0], years[1] + 1)))
    return {
        "years": years,
        "summary": floor_summary(g),
        "by_industry": summary_by(g, "bea_line"),
        "by_cow": summary_by(g, "cow_class"),
        "leakage": leakage(g),
        "households": household_table(sub, thresholds, cfg["mit"]["hours_full_time"], floor_type),
        "capacity": cap.capacity_table(cap.gap_by_line(g, cfg), pm, cfg["crosswalk"]["gov_line"]),
        "gos_tests": cap.gos_tests(g, pm, cfg),
    }


def run(cfg, raw: Path = Path("data/raw"), out: Path = Path("data/out")) -> Path:
    cpi_json = json.loads((raw / "bls" / f"{cfg['cpi']['series']}.json").read_text())
    persons = load_persons(cfg, raw)
    fam = family_units(persons, cfg).select(*UNIT_KEYS, "household", "children_over_cap")
    xw = pl.read_csv(CROSSWALK_PATH, infer_schema_length=0)
    u_all = apply_crosswalk(build_universe(persons, cpi_json, cfg).join(fam, on=UNIT_KEYS, how="left"), xw)
    if u_all["household"].null_count():
        raise ValueError(f"{u_all['household'].null_count()} universe workers have no family unit")
    u = u_all.filter(~pl.col("outlier"))

    thresholds = load_thresholds(cfg)
    floor = thresholds[cfg["mit"]["floor_type"]]
    bea = load_bea(cfg, raw / "bea")
    fa = load_fixed_assets(cfg, raw / "bea" / "api")
    industries = pl.read_csv(cap.INDUSTRIES_PATH, infer_schema_length=0)
    gos_resid = cap.validate_gos_method(bea, cfg)
    panel = cap.to_target_dollars(cap.bea_panel(bea, fa, industries, cfg), cpi_json, cfg)

    windows = {name: _window(u, panel, thresholds, cfg["years"][name], cfg) for name in ("pool", "subset")}
    sens = run_sensitivities(u_all, {"bea": bea, "cpi_json": cpi_json}, cfg,
                            u_self=build_universe(persons, cpi_json, cfg, include_self_employed=True))
    pool = cfg["years"]["pool"]
    window_diff = window_difference(add_floor_gap(year_subset(u, pool, pool), floor), cfg["years"]["subset"], pool,
                                    cfg["moe_z"])

    bea_w, _ = bea_wages_2024usd(bea, cpi_json, cfg)
    survey_bea = {"pct": wage_check(persons, bea_w, cfg)["pct_diff"],
                  "pct_like": wage_check(persons, bea_w, cfg, cow=cfg["checkpoint"]["wage_check_cow_bea"])["pct_diff"]}

    pool_g = add_floor_gap(u, floor)
    by_src = []
    for src in ("ms", "other"):
        s = pool_g.filter(pl.col("src") == src)
        fs = floor_summary(s)
        by_src.append({"src": src, "records": s.height, "workers": fs["workers"],
                       "wages": weighted_total(s, "earnings"), "below": fs["below"], "gap": fs["total_gap"]})
    labels = dict(zip(industries["line"], industries["label"]))
    suppressed = (panel.filter(pl.col("line").is_in(list(labels)) & (pl.col("gdp").is_null() | pl.col("comp").is_null()))
                  .select("line", "year", gdp_suppressed=pl.col("gdp").is_null(), comp_suppressed=pl.col("comp").is_null()))
    over_cap = u.filter(pl.col("children_over_cap"))
    minors = u.filter(pl.col("AGEP") < cfg["households"]["adult_age"])
    qa = {
        "by_src": by_src,
        "outliers": (u_all["outlier"].sum(), _weighted_count(u_all.filter(pl.col("outlier")))),
        "self_employed": self_employed_count(persons, cfg),
        "crosswalk": {"pairs_in_data": u_all.select("COW", "NAICSP").unique().height, "crosswalk_rows": xw.height},
        "gos_resid": gos_resid,
        "suppressed": suppressed,
        "children_over_cap": (over_cap.height, _weighted_count(over_cap)),
        "minors": (minors.height, _weighted_count(minors)),
    }
    ctx = {"cfg": cfg, "floor": floor, "thresholds": thresholds, "labels": labels, "windows": windows,
           "sensitivities": sens, "window_diff": window_diff, "survey_bea": survey_bea, "u": pool_g, "qa": qa}
    return write_results(ctx, out)
