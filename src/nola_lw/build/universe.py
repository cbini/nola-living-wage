"""SPEC §11.3: place-of-work worker universe and hourly wages."""
from pathlib import Path

import polars as pl

from nola_lw.analysis.se import weighted_total
from nola_lw.fetch.bls import cpi_factor
from nola_lw.fetch.pums import PERSON_VARS, REP_VARS, scan_persons


def load_persons(cfg, raw: Path = Path("data/raw")) -> pl.DataFrame:
    """Every person, LA + MS in full plus other-state commuter households, tagged `src`."""
    pums = raw / "pums"
    bulk = [(st, pums / f"psam_p{cfg['pums']['bulk_state_fips'][st]}.csv") for st in cfg["pums"]["bulk_states"]]
    other = pums / "other_states.parquet"
    missing = [str(f) for _, f in bulk if not f.exists()]
    if not other.exists():
        missing.append(str(other))
    done = set((pums / "other_states.done").read_text().split()) if (pums / "other_states.done").exists() else set()
    not_done = sorted(set(cfg["pums"]["other_states"]) - done)
    if not_done:
        missing.append(f"other-state PUMS not fetched: {', '.join(not_done)}")
    if missing:
        raise FileNotFoundError("; ".join(missing))
    frames = [scan_persons(f).with_columns(src=pl.lit(st)) for st, f in bulk]
    frames.append(pl.scan_parquet(other).select(PERSON_VARS + REP_VARS).with_columns(src=pl.lit("other")))
    return pl.concat(frames).collect()


def build_universe(persons: pl.DataFrame, cpi_json: dict, cfg, include_self_employed: bool = False) -> pl.DataFrame:
    """One row per wage/salary worker at Orleans place of work, with hourly wage in MIT's price basis.

    `include_self_employed` (a sensitivity only) adds `universe.cow_self` workers and pays everyone
    wages plus self-employment income (`SEMP`); a net loss or zero income drops the person."""
    o, u, c = cfg["orleans"], cfg["universe"], cfg["cpi"]
    factor = cpi_factor(cpi_json, c["base_year"], c["target"])
    cow, pay = u["cow_wage"], pl.col("WAGP")
    if include_self_employed:
        cow, pay = cow + u["cow_self"], pay + pl.col("SEMP").fill_null(0)
    df = persons.filter(
        (pl.col("POWSP") == o["powsp"]) & pl.col("POWPUMA").is_in(o["powpuma"])
        & pl.col("COW").is_in(cow) & (pay > 0) & (pl.col("WKHP") > 0) & (pl.col("WKWN") > 0)
    )
    df = df.with_columns(
        year=pl.col("SERIALNO").str.slice(0, 4),
        cow_class=pl.col("COW").replace(u["cow_class"]),
        residence=pl.when((pl.col("STATE") == o["state_fips"]) & pl.col("PUMA").is_in(o["residence_pumas"]))
                    .then(pl.lit("orleans"))
                  .when(pl.col("STATE") == o["state_fips"])
                    .then(pl.lit("other_la"))
                  .otherwise(pl.lit("out_of_state")),
    )
    df = df.with_columns(
        earnings=pay * pl.col("ADJINC") / 1e6 * factor,
        hours=pl.col("WKHP") * pl.col("WKWN"),
    )
    df = df.with_columns(wage_hr=pl.col("earnings") / pl.col("hours"))
    return df.with_columns(outlier=(pl.col("wage_hr") < u["wage_min"]) | (pl.col("wage_hr") > u["wage_max"]))


def self_employed_count(persons: pl.DataFrame, cfg) -> tuple[float, float]:
    """Weighted count (and SE) of place-of-work-Orleans self-employed and unpaid family workers."""
    o, u = cfg["orleans"], cfg["universe"]
    df = persons.filter((pl.col("POWSP") == o["powsp"]) & pl.col("POWPUMA").is_in(o["powpuma"])
                        & pl.col("COW").is_in(u["cow_self"] + u["cow_unpaid"])).with_columns(one=pl.lit(1.0))
    return weighted_total(df, "one")
