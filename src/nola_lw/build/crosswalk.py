"""SPEC §8: (COW, NAICSP) -> BEA CAGDP2 line crosswalk. COW 3-5 (government) always map to
the government line; everyone else maps by the 2-char NAICSP prefix (config.crosswalk)."""
import polars as pl


def draft_crosswalk(pairs: pl.DataFrame, cfg) -> pl.DataFrame:
    """One row per distinct (COW, NAICSP) pair in `pairs` -> bea_line."""
    c = cfg["crosswalk"]
    cow_public, prefix_map, gov_line = cfg["universe"]["cow_public"], c["prefix_to_line"], c["gov_line"]
    rows = []
    for r in pairs.select("COW", "NAICSP").unique().sort("COW", "NAICSP").iter_rows(named=True):
        cow, naicsp = r["COW"], r["NAICSP"]
        if cow in cow_public:
            line = gov_line
        else:
            prefix = naicsp[:2]
            if prefix == "92":
                raise ValueError(f"non-government COW={cow} with public-administration NAICSP={naicsp}")
            if prefix not in prefix_map:
                raise ValueError(f"unmapped NAICSP prefix {prefix!r} (COW={cow}, NAICSP={naicsp})")
            line = prefix_map[prefix]
        rows.append({"COW": cow, "NAICSP": naicsp, "bea_line": line})
    return pl.DataFrame(rows, schema={"COW": pl.Utf8, "NAICSP": pl.Utf8, "bea_line": pl.Utf8})


def apply_crosswalk(u: pl.DataFrame, xw: pl.DataFrame) -> pl.DataFrame:
    """Add `bea_line` to `u` by joining on (COW, NAICSP). Raises on any pair missing from `xw`
    or duplicated within `xw`."""
    dupes = xw.group_by(["COW", "NAICSP"]).len().filter(pl.col("len") > 1)
    if dupes.height:
        pairs = ", ".join(f"({r['COW']}, {r['NAICSP']})" for r in dupes.iter_rows(named=True))
        raise ValueError(f"duplicate (COW, NAICSP) pairs in crosswalk: {pairs}")
    joined = u.join(xw, on=["COW", "NAICSP"], how="left")
    missing = joined.filter(pl.col("bea_line").is_null()).select("COW", "NAICSP").unique()
    if missing.height:
        pairs = ", ".join(f"({r['COW']}, {r['NAICSP']})" for r in missing.iter_rows(named=True))
        raise ValueError(f"(COW, NAICSP) pairs missing from crosswalk: {pairs}")
    return joined
