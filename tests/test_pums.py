import io
import zipfile
from pathlib import Path

import polars as pl

from nola_lw.config import load_config
from nola_lw.fetch.pums import fetch_other_states, keep_la_worker_households, read_persons

FIX = Path(__file__).parent / "fixtures" / "pums_tiny.csv"


def test_codes_keep_leading_zeros():
    df = read_persons(FIX)
    w = df.filter(pl.col("SPORDER") == "1").row(0, named=True)
    assert w["POWSP"] == "022"
    assert w["POWPUMA"] == "02400"
    assert w["NAICSP"] == "722Z"
    assert "4MS" in df["NAICSP"].to_list()
    assert df.schema["PWGTP"] == pl.Int64 and df.schema["PWGTP80"] == pl.Int64


def test_keep_la_worker_households():
    kept = keep_la_worker_households(read_persons(FIX), "022")
    assert set(kept["SERIALNO"]) == {"2022HU0000001"}
    assert kept.height == 3  # worker, spouse, and child with null POWSP


def _fake_zip_download(calls):
    def fake(url, dest, **kw):
        calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        st = url.rsplit("csv_p", 1)[1][:2]
        with zipfile.ZipFile(dest, "w") as z:
            z.writestr(f"psam_p_{st}.csv", FIX.read_text())
        return dest
    return fake


def test_other_states_resumes(tmp_path):
    cfg = load_config()
    cfg["pums"]["other_states"] = ["ak", "al"]
    cfg["pums"]["min_free_disk_gb"] = 0
    calls = []
    out = fetch_other_states(cfg, raw=tmp_path, download_fn=_fake_zip_download(calls))
    assert len(calls) == 2
    df = pl.read_parquet(out)
    assert df.height == 6  # one matching household (3 people) from each state
    assert not list(tmp_path.glob("*.zip")) and not list(tmp_path.glob("**/*.csv"))
    fetch_other_states(cfg, raw=tmp_path, download_fn=_fake_zip_download(calls))
    assert len(calls) == 2
    assert pl.read_parquet(out).height == 6


def test_other_states_crash_before_done_does_not_duplicate(tmp_path):
    cfg = load_config()
    cfg["pums"]["other_states"] = ["ak"]
    cfg["pums"]["min_free_disk_gb"] = 0
    calls = []
    out = fetch_other_states(cfg, raw=tmp_path, download_fn=_fake_zip_download(calls))
    (tmp_path / "other_states.done").unlink()  # crash after parquet write, before .done
    fetch_other_states(cfg, raw=tmp_path, download_fn=_fake_zip_download(calls))
    assert pl.read_parquet(out).height == 3
