"""Survey pay vs. employer-reported pay: the BLS OEWS metro percentiles as an independent check."""
import copy
import json
from pathlib import Path

import numpy as np
import polars as pl

from nola_lw.analysis.gaps import year_subset
from nola_lw.analysis.se import replicate_estimate
from nola_lw.build.universe import build_universe
from nola_lw.fetch.bls import _monthly, oews_path
from nola_lw.fetch.ipums import read_composition

QUANTILES = {"p10": 0.10, "p25": 0.25, "p50": 0.50, "p75": 0.75, "p90": 0.90}


def oews_percentiles(oews_json: dict, cpi_json: dict, cfg) -> dict[str, float]:
    """OEWS hourly wage percentiles (and employment) for the reference month, moved to MIT's price basis."""
    o = cfg["oews"]
    m = _monthly(cpi_json)
    factor = m[cfg["cpi"]["target"]] / m[o["reference_month"]]
    by_dt = {s["seriesID"][-2:]: s["data"] for s in oews_json["Results"]["series"]}  # datatype = last 2 chars
    out = {}
    for key, dt in o["datatypes"].items():
        rows = [r for r in by_dt.get(dt, []) if r["year"] == str(o["year"])]
        if not rows:
            raise ValueError(f"OEWS {key} (datatype {dt}) missing for {o['year']}")
        v = float(rows[0]["value"].replace(",", ""))
        out[key] = v if key == "employment" else v * factor
    return out


def share_below(pcts: dict[str, float], x: float) -> float | None:
    """Share of jobs paying less than `x`, interpolated between published percentiles; None outside them."""
    xs, qs = [pcts[k] for k in QUANTILES], list(QUANTILES.values())
    return None if x < xs[0] or x > xs[-1] else float(np.interp(x, xs, qs))


def metro_powpumas(comp: pl.DataFrame, cfg) -> dict:
    """In-state POWPUMAs made up only of metro counties, and those that mix metro and non-metro counties."""
    o, metro = cfg["orleans"], set(cfg["oews"]["metro_counties"])
    groups = (comp.filter((pl.col("st") == o["state_fips"]) & (pl.col("pwst") == o["powsp"]))
              .group_by("powpuma").agg(pl.col("county").unique()).iter_rows())
    inside, mixed = [], []
    for powpuma, counties in groups:
        c = set(counties)
        if c <= metro:
            inside.append(powpuma)
        elif c & metro:
            mixed.append(powpuma)
    return {"powpumas": sorted(inside), "mixed": sorted(mixed)}


def _wq(d: pl.DataFrame, w: str, q: float) -> float:
    s = d.select("wage_hr", w).sort("wage_hr")
    c = s[w].cum_sum().to_numpy()
    return float(s["wage_hr"][int(np.searchsorted(c, c[-1] * q))])


def survey_percentiles(u: pl.DataFrame, floor: float) -> dict[str, tuple[float, float]]:
    """Weighted hourly-wage percentiles and the share below `floor`, each (est, se)."""
    out = {k: replicate_estimate(u, lambda d, w, q=q: _wq(d, w, q)) for k, q in QUANTILES.items()}
    out["share_below"] = replicate_estimate(u, lambda d, w: d.filter(pl.col("wage_hr") < floor)[w].sum() / d[w].sum())
    return out


def crosscheck(persons: pl.DataFrame, u_pool: pl.DataFrame, cpi_json: dict, cfg, floor: float,
               raw: Path = Path("data/raw")) -> dict:
    """Survey percentiles for Orleans and for metro workplaces next to the OEWS metro percentiles."""
    comp = read_composition(raw / "ipums" / Path(cfg["pums"]["powpuma_composition_url"]).name)
    mp = metro_powpumas(comp, cfg)
    cfg_m = copy.deepcopy(cfg)
    cfg_m["orleans"]["powpuma"] = mp["powpumas"]
    pool = cfg["years"]["pool"]
    um = year_subset(build_universe(persons, cpi_json, cfg_m).filter(~pl.col("outlier")), pool, pool)
    oews = oews_percentiles(json.loads(oews_path(cfg, raw / "bls").read_text()), cpi_json, cfg)
    return {"metro": mp, "oews": oews, "oews_share_below": share_below(oews, floor),
            "survey_orleans": survey_percentiles(u_pool, floor), "survey_metro": survey_percentiles(um, floor)}
