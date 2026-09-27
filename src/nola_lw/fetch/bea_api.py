"""BEA API client: FAAt304ESI depreciation (national CFC shares). NoteRef-aware, same
suppression rule as the bulk zips (fetch.bea) -- a suppression flag beats DataValue "0"."""
import json
import os
import time
from pathlib import Path

import polars as pl

from nola_lw.fetch.common import download

RAW = Path("data/raw/bea/api")
SUPPRESSION_FLAGS = ["(D)", "(NA)", "(NM)", "(L)"]  # mirrors config bea.suppression_flags

_last_call = 0.0


def _throttle(min_interval_s: float) -> None:
    global _last_call
    wait = min_interval_s - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def check_for_error(obj) -> None:
    """Raise if an "Error" key appears anywhere in the (possibly nested) response."""
    if isinstance(obj, dict):
        if "Error" in obj:
            raise RuntimeError(f"BEA API error: {obj['Error']}")
        for v in obj.values():
            check_for_error(v)
    elif isinstance(obj, list):
        for v in obj:
            check_for_error(v)


def parse_api(data: list[dict], unit_mult_key: str = "UNIT_MULT") -> pl.DataFrame:
    out = []
    for rec in data:
        note = rec.get("NoteRef") or ""
        flag = next((f for f in SUPPRESSION_FLAGS if f in note), None)
        if flag:
            value = None
        else:
            value = float(rec["DataValue"].replace(",", "")) * 10 ** int(rec[unit_mult_key])
        out.append({"table": rec["TableName"], "line_code": rec["LineNumber"], "line_desc": rec["LineDescription"],
                    "year": int(rec["TimePeriod"]), "value": value, "flag": flag})
    schema = {"table": pl.Utf8, "line_code": pl.Utf8, "line_desc": pl.Utf8,
              "year": pl.Int64, "value": pl.Float64, "flag": pl.Utf8}
    return pl.DataFrame(out, schema=schema)


def fetch_fixed_assets(cfg, raw: Path = RAW) -> Path:
    b = cfg["bea"]
    y0, y1 = cfg["years"]["pool"]
    years = ",".join(str(y) for y in range(y0, y1 + 1))
    fa = b["fixed_assets"]
    params = {"UserID": os.environ["BEA_API_KEY"], "method": "GetData", "DataSetName": fa["dataset"],
              "TableName": fa["table"], "Year": years, "ResultFormat": "JSON"}
    dest = raw / f"{fa['table']}.json"
    _throttle(b["api_min_interval_s"])
    dest = download(b["api_base"], dest, params=params)
    check_for_error(json.loads(dest.read_text()))
    return dest


def load_fixed_assets(cfg, raw: Path = RAW) -> pl.DataFrame:
    fa = cfg["bea"]["fixed_assets"]
    dest = raw / f"{fa['table']}.json"
    data = json.loads(dest.read_text())["BEAAPI"]["Results"]["Data"]
    return parse_api(data)
