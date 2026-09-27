"""BLS CPI-U South (keyless v1, or v2 when BLS_API_KEY is set). Missing months are errors, never fallbacks."""
import json
import os
from pathlib import Path

import httpx

from nola_lw.fetch.common import record

V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
V2 = "https://api.bls.gov/publicAPI/v2/timeseries/data/"


def check_response(d: dict) -> dict:
    if d.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS request failed: {d.get('status')}: {d.get('message')}")
    return d


def _monthly(cpi_json: dict) -> dict[str, float]:
    series = cpi_json["Results"]["series"][0]["data"]
    return {f"{r['year']}-{r['period'][1:]}": float(r["value"]) for r in series if r["period"] != "M13"}


def annual_mean(cpi_json: dict, year: int) -> float:
    m = _monthly(cpi_json)
    missing = [f"{year}-{i:02d}" for i in range(1, 13) if f"{year}-{i:02d}" not in m]
    if missing:
        raise ValueError(f"CPI {year}: months missing {missing}")
    return sum(m[f"{year}-{i:02d}"] for i in range(1, 13)) / 12


def cpi_factor(cpi_json: dict, base_year: int, target: str) -> float:
    m = _monthly(cpi_json)
    if target not in m:
        raise ValueError(f"CPI target month {target} not in series")
    return m[target] / annual_mean(cpi_json, base_year)


def fetch_cpi(cfg, out_dir: Path = Path("data/raw/bls")) -> Path:
    c = cfg["cpi"]
    start, end = c["fetch_years"]
    body = {"seriesid": [c["series"]], "startyear": str(start), "endyear": str(end)}
    key = os.environ.get("BLS_API_KEY")
    url = V2 if key else V1
    if key:
        body["registrationkey"] = key  # body only; never written to disk
    r = httpx.post(url, json=body, timeout=120)
    r.raise_for_status()
    d = check_response(r.json())
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{c['series']}.json"
    dest.write_text(json.dumps(d, indent=1))
    record(f"{url}?series={c['series']}&start={start}&end={end}", dest)
    return dest
