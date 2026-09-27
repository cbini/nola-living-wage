"""ACS 5-year PUMS bulk files: LA and MS in full, other states filtered to households with an LA worker."""
import shutil
import zipfile
from pathlib import Path

import polars as pl

from nola_lw.fetch.common import download

RAW = Path("data/raw/pums")
CODE_VARS = ["SERIALNO", "SPORDER", "COW", "NAICSP", "POWSP", "POWPUMA", "STATE", "PUMA", "RELSHIPP", "SFN", "SFR"]
NUM_VARS = ["PWGTP", "WAGP", "ADJINC", "WKHP", "WKWN", "AGEP", "SEMP"]
PERSON_VARS = CODE_VARS + NUM_VARS
REP_VARS = [f"PWGTP{i}" for i in range(1, 81)]
SCHEMA = {c: pl.Utf8 for c in CODE_VARS} | {c: pl.Int64 for c in NUM_VARS + REP_VARS}


def scan_persons(path: Path) -> pl.LazyFrame:
    return pl.scan_csv(path, schema_overrides=SCHEMA).select(PERSON_VARS + REP_VARS)


def read_persons(path: Path) -> pl.DataFrame:
    return scan_persons(path).collect()


def keep_la_worker_households(df, powsp: str):
    """Every person in a household (SERIALNO) with at least one member working in state `powsp`."""
    serials = df.filter(pl.col("POWSP") == powsp).select("SERIALNO").unique()
    return df.join(serials, on="SERIALNO", how="semi")


def _extract(z: Path, dest: Path) -> list[Path]:
    with zipfile.ZipFile(z) as zf:
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        zf.extractall(dest, members=names)
    return [dest / n for n in names]


def fetch_bulk(cfg, raw: Path = RAW) -> list[Path]:
    p = cfg["pums"]
    out = [download(u, raw / Path(u).name) for u in (p["dictionary_url"], p["tract_to_puma_url"])]
    for st in p["bulk_states"]:
        for kind in ("p", "h"):
            z = download(f"{p['bulk_base']}/csv_{kind}{st}.zip", raw / f"csv_{kind}{st}.zip")
            out += _extract(z, raw)
    return out


def _check_disk(path: Path, min_gb: float) -> None:
    free = shutil.disk_usage(path).free / 1e9
    if free < min_gb:
        raise RuntimeError(f"only {free:.1f} GB free at {path}; need {min_gb} GB (pums.min_free_disk_gb)")


def fetch_other_states(cfg, raw: Path = RAW, download_fn=download) -> Path:
    p, powsp = cfg["pums"], cfg["orleans"]["powsp"]
    raw.mkdir(parents=True, exist_ok=True)
    out, done_file = raw / "other_states.parquet", raw / "other_states.done"
    done = set(done_file.read_text().split()) if done_file.exists() else set()
    for st in p["other_states"]:
        if st in done:
            continue
        _check_disk(raw, p["min_free_disk_gb"])
        z = download_fn(f"{p['bulk_base']}/csv_p{st}.zip", raw / f"csv_p{st}.zip")
        tmp = raw / f"_tmp_{st}"
        csvs = _extract(z, tmp)
        kept = pl.concat([keep_la_worker_households(scan_persons(c), powsp).collect() for c in csvs])
        print(f"pums {st}: kept {kept.height} persons", flush=True)
        if out.exists():
            kept = pl.concat([pl.read_parquet(out), kept])
        kept.write_parquet(out.with_suffix(".tmp"))
        out.with_suffix(".tmp").replace(out)
        with done_file.open("a") as f:  # written only after the parquet holds this state
            f.write(st + "\n")
        shutil.rmtree(tmp)
        z.unlink()
    if not out.exists():
        pl.DataFrame(schema={c: SCHEMA[c] for c in PERSON_VARS + REP_VARS}).write_parquet(out)
    return out
