"""SPEC §5, §11.5: MIT family units (Decisions 1-3). See analysis/gaps.py for household_table."""
import csv
from pathlib import Path

import polars as pl

REFERENCE = "20"
SPOUSE_PARTNER = ["21", "22", "23", "24"]
OWN_CHILD = ["25", "26", "27"]
SUBFAMILY_ADULT = ["1", "2", "3"]
SUBFAMILY_CHILD = ["4", "5", "6"]


def family_units(persons: pl.DataFrame, cfg) -> pl.DataFrame:
    """One row per person: `unit_id`, `adults`, `children` (capped), `children_over_cap`, `working`, `household`."""
    max_children = cfg["households"]["max_children"]

    is_gq = pl.col("SERIALNO").str.contains("GQ")
    sfn = pl.when(pl.col("SFN").is_in([None, "", "0"])).then(None).otherwise(pl.col("SFN"))
    in_subfamily = sfn.is_not_null() & ~is_gq
    is_reference = pl.col("RELSHIPP") == REFERENCE
    is_spouse = pl.col("RELSHIPP").is_in(SPOUSE_PARTNER)
    is_own_child_minor = pl.col("RELSHIPP").is_in(OWN_CHILD) & (pl.col("AGEP") < 18)
    is_ref_family_named = is_reference | is_spouse | is_own_child_minor
    is_unattached_minor = (pl.col("AGEP") < 18) & ~in_subfamily & ~is_gq & ~is_ref_family_named
    is_working = (pl.col("WAGP") > 0) | (pl.col("SEMP") != 0)

    p = persons.with_columns(
        unit_id=(
            pl.when(is_gq).then(pl.col("SERIALNO") + "_" + pl.col("SPORDER"))
            .when(in_subfamily).then(pl.col("SERIALNO") + "_SF" + sfn)
            .when(is_ref_family_named | is_unattached_minor).then(pl.col("SERIALNO") + "_REF")
            .otherwise(pl.col("SERIALNO") + "_" + pl.col("SPORDER"))
        ),
        is_adult_in_unit=(
            is_gq
            | (in_subfamily & pl.col("SFR").is_in(SUBFAMILY_ADULT))
            | (~in_subfamily & ~is_gq & is_ref_family_named & ~is_own_child_minor)
            | (~in_subfamily & ~is_gq & ~is_ref_family_named & ~is_unattached_minor)
        ),
        is_child_in_unit=(
            (in_subfamily & pl.col("SFR").is_in(SUBFAMILY_CHILD))
            | (~in_subfamily & ~is_gq & (is_own_child_minor | is_unattached_minor))
        ),
        is_working=is_working,
    )

    agg = p.group_by(["src", "unit_id"]).agg(
        adults=pl.col("is_adult_in_unit").sum(),
        children_actual=pl.col("is_child_in_unit").sum(),
        adults_working=(pl.col("is_adult_in_unit") & pl.col("is_working")).sum(),
    ).with_columns(
        children_over_cap=pl.col("children_actual") > max_children,
        children=pl.col("children_actual").clip(upper_bound=max_children),
        working=pl.when((pl.col("adults") == 2) & (pl.col("adults_working") == 2)).then(2).otherwise(1),
    ).with_columns(
        household=pl.concat_str([pl.lit("a"), pl.col("adults").cast(pl.Utf8), pl.lit("_w"),
                                  pl.col("working").cast(pl.Utf8), pl.lit("_c"), pl.col("children").cast(pl.Utf8)])
    )

    return p.join(agg, on=["src", "unit_id"]).select(
        "SERIALNO", "SPORDER", "src", "unit_id", "adults", "children", "children_over_cap", "working", "household"
    )


def load_thresholds(cfg, snapshot_dir: Path = Path("data/snapshots")) -> dict[str, float]:
    """Living-wage hourly thresholds by household key, from the latest committed county snapshot."""
    area = cfg["mit"]["county_path"].replace("/", "_")
    snaps = sorted(snapshot_dir.glob(f"mit_{area}_*.csv"))
    if not snaps:
        raise FileNotFoundError(f"no MIT snapshot data/snapshots/mit_{area}_*.csv")
    rows = list(csv.DictReader(snaps[-1].open()))
    return {r["household"]: float(r["hourly"]) for r in rows}
