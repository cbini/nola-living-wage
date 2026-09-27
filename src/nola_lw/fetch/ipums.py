"""Census/IPUMS official 2020 county-to-POWPUMA composition file (a legacy .xls)."""
from pathlib import Path

import polars as pl

from nola_lw.fetch.common import download

RAW = Path("data/raw/ipums")
COLUMNS = ["st", "county", "pwst", "powpuma"]


def fetch_composition(cfg, raw: Path = RAW) -> Path:
    url = cfg["pums"]["powpuma_composition_url"]
    return download(url, raw / Path(url).name)


def read_composition(path: Path) -> pl.DataFrame:
    if path.suffix == ".csv":
        df = pl.read_csv(path, infer_schema_length=0)
    else:
        df = pl.read_excel(path)
    df.columns = COLUMNS
    return df.select(pl.all().cast(pl.Utf8))


def orleans_powpumas(comp: pl.DataFrame, cfg) -> dict:
    o = cfg["orleans"]
    home = comp.filter((pl.col("st") == o["state_fips"]) & (pl.col("county") == o["county_fips"])
                       & (pl.col("pwst") == o["powsp"]))
    powpumas = sorted(home["powpuma"].unique())
    counties = sorted(comp.filter((pl.col("pwst") == o["powsp"]) & pl.col("powpuma").is_in(powpumas))["county"].unique())
    return {"powpumas": powpumas, "counties": counties}
