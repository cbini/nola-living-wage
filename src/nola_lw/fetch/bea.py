"""BEA regional bulk ZIPs. Suppressed cells ((D), (NA), ...) are null with the flag kept — never zero."""
import csv
import zipfile
from pathlib import Path

import polars as pl

from nola_lw.fetch.common import download

RAW = Path("data/raw/bea")
ID_COLS = ["GeoFIPS", "GeoName", "Region", "TableName", "LineCode", "IndustryClassification", "Description", "Unit"]


def fetch_zips(cfg, raw: Path = RAW) -> list[Path]:
    b = cfg["bea"]
    out = []
    for name in b["zips"]:
        z = download(f"{b['zip_base']}/{name}.zip", raw / f"{name}.zip")
        with zipfile.ZipFile(z) as zf:
            zf.extractall(raw / name)
        out.append(z)
    return out


def parse_bea_csv(path: Path, geo: str, bea_cfg: dict) -> pl.DataFrame:
    with open(path, encoding="latin-1", newline="") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    if header[: len(ID_COLS)] != ID_COLS:
        raise ValueError(f"{path}: unexpected BEA header {header[:len(ID_COLS)]}")
    years = header[len(ID_COLS):]
    flags, scale = set(bea_cfg["suppression_flags"]), bea_cfg["unit_scale"]
    out = []
    for r in rows[1:]:
        if len(r) != len(header):  # footnote/source lines at the end
            if r and r[0].strip().strip('"') == geo:
                raise ValueError(f"{path}: malformed row for {geo}: {len(r)} fields, header has {len(header)}")
            continue
        rec = dict(zip(header, r))
        if rec["GeoFIPS"].strip().strip('"') != geo:
            continue
        unit = rec["Unit"].strip()
        if unit not in scale:
            raise ValueError(f"{path}: unknown unit {unit!r} (add it to bea.unit_scale)")
        for y in years:
            cell = rec[y].strip()
            if cell in flags:
                value, flag = None, cell
            else:
                try:
                    value, flag = float(cell) * scale[unit], None
                except ValueError:
                    raise ValueError(f"{path}: unrecognised cell {cell!r} (line {rec['LineCode']}, {y})") from None
            out.append({"table": rec["TableName"].strip(), "line_code": rec["LineCode"].strip(),
                        "line_desc": rec["Description"].strip(), "geo": geo, "year": int(y),
                        "value": value, "flag": flag})
    schema = {"table": pl.Utf8, "line_code": pl.Utf8, "line_desc": pl.Utf8, "geo": pl.Utf8,
              "year": pl.Int64, "value": pl.Float64, "flag": pl.Utf8}
    return pl.DataFrame(out, schema=schema)


def _table_file(raw: Path, table: str, st: str) -> Path:
    # per-state file when BEA ships one (SAINC1 has only the all-areas file)
    for pattern in (f"*/{table}_{st}_*.csv", f"*/{table}__ALL_AREAS_*.csv"):
        hits = sorted(raw.glob(pattern))
        if len(hits) > 1:
            raise FileNotFoundError(f"BEA {table}: several files match {pattern}: {hits}")
        if hits:
            return hits[0]
    raise FileNotFoundError(f"BEA {table}: no {table}_{st}_*.csv or {table}__ALL_AREAS_*.csv under {raw}")


def load_bea(cfg, raw: Path = RAW) -> pl.DataFrame:
    b = cfg["bea"]
    y0, y1 = cfg["years"]["pool"]
    frames = [parse_bea_csv(_table_file(raw, t, b["state_abbr"]), b["county_geo"], b) for t in b["county_tables"]]
    frames += [parse_bea_csv(_table_file(raw, t, b["state_abbr"]), b["state_geo"], b) for t in b["state_tables"]]
    frames.append(parse_bea_csv(_table_file(raw, "SAGDP2", b["national_abbr"]), b["national_geo"], b))
    return pl.concat(frames).filter(pl.col("year").is_between(y0, y1))
