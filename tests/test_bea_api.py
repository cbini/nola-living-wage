import csv
import json
from pathlib import Path

import httpx
import pytest

from nola_lw.config import load_config
from nola_lw.fetch.bea_api import check_for_error, fetch_fixed_assets, parse_api

FIX = Path(__file__).parent / "fixtures" / "bea_api_fa.json"
CFG = load_config()
FLAGS = CFG["bea"]["suppression_flags"]


def test_api_suppressed_zero_is_null():
    data = [{"TableName": "FAAt304ESI", "LineNumber": "1", "LineDescription": "x",
             "TimePeriod": "2020", "UNIT_MULT": "6", "DataValue": "0", "NoteRef": "(D)"}]
    df = parse_api(data, FLAGS)
    r = df.row(0, named=True)
    assert r["value"] is None
    assert r["flag"] == "(D)"


def test_api_literal_zero_stays_zero():
    data = [{"TableName": "FAAt304ESI", "LineNumber": "1", "LineDescription": "x",
             "TimePeriod": "2020", "UNIT_MULT": "6", "DataValue": "0", "NoteRef": ""}]
    df = parse_api(data, FLAGS)
    r = df.row(0, named=True)
    assert r["value"] == 0.0
    assert r["flag"] is None


def test_api_units_and_commas():
    data = [{"TableName": "FAAt304ESI", "LineNumber": "1", "LineDescription": "x",
             "TimePeriod": "2020", "UNIT_MULT": "6", "DataValue": "3,992,907", "NoteRef": ""}]
    df = parse_api(data, FLAGS)
    assert df.row(0, named=True)["value"] == 3_992_907 * 10**6


def test_api_flags_are_caller_supplied():
    """No suppression flag list lives in bea_api.py; a caller's own list is honored as-is."""
    data = [{"TableName": "t", "LineNumber": "1", "LineDescription": "x",
             "TimePeriod": "2020", "UNIT_MULT": "0", "DataValue": "0", "NoteRef": "(WEIRD)"}]
    assert parse_api(data, ["(WEIRD)"]).row(0, named=True)["flag"] == "(WEIRD)"
    assert parse_api(data, ["(D)"]).row(0, named=True)["flag"] is None


def test_api_error_is_fatal():
    with pytest.raises(RuntimeError):
        check_for_error({"BEAAPI": {"Results": {"Error": {"APIErrorCode": "1", "APIErrorDescription": "bad"}}}})


def test_api_error_nested_is_fatal():
    check_for_error({"BEAAPI": {"Results": {"Data": []}}})  # no Error key: fine
    with pytest.raises(RuntimeError):
        check_for_error({"BEAAPI": {"Request": {"Error": {"APIErrorCode": "2"}}}})


def test_fixture_has_fabricated_suppressed_cell():
    """The fixture is a trimmed REAL FAAt304ESI response, with one NoteRef "(D)" cell we
    fabricated by hand to exercise the suppression path (marked here, not left silent)."""
    data = json.loads(FIX.read_text())["BEAAPI"]["Results"]["Data"]
    df = parse_api(data, FLAGS)
    suppressed = df.filter(df["flag"] == "(D)")
    assert suppressed.height == 1  # fabricated cell
    assert suppressed.row(0, named=True)["value"] is None


def _client(body: dict):
    def handler(request):
        return httpx.Response(200, json=body)
    return httpx.Client(transport=httpx.MockTransport(handler))


def _echoing_body(userid: str, data=None, error=None) -> dict:
    results = {"Error": error} if error else {"Data": data if data is not None else []}
    return {"BEAAPI": {"Request": {"RequestParam": [
                {"ParameterName": "USERID", "ParameterValue": userid},
                {"ParameterName": "METHOD", "ParameterValue": "GETDATA"},
            ]},
            "Results": results}}


def test_fetch_scrubs_echoed_userid_from_saved_file(tmp_path, monkeypatch):
    """BEA echoes the request under BEAAPI.Request.RequestParam (ParameterName USERID) --
    the saved file, and the manifest's hash of it, must never carry the real key."""
    import hashlib

    monkeypatch.setenv("BEA_API_KEY", "SUPER-SECRET-KEY")
    manifest = tmp_path / "manifest.csv"
    body = _echoing_body("SUPER-SECRET-KEY", data=[{"TableName": "t", "LineNumber": "1",
                          "LineDescription": "x", "TimePeriod": "2020", "UNIT_MULT": "0",
                          "DataValue": "1", "NoteRef": ""}])
    cfg = {**CFG, "bea": {**CFG["bea"], "api_min_interval_s": 0}}
    dest = fetch_fixed_assets(cfg, raw=tmp_path, client=_client(body), manifest=manifest)
    text = dest.read_text()
    assert "SUPER-SECRET-KEY" not in text
    assert '"ParameterName": "USERID"' in text  # scrubbed, not stripped out entirely

    rows = list(csv.DictReader(manifest.open()))
    assert "SUPER-SECRET-KEY" not in manifest.read_text()
    assert rows[0]["sha256"] == hashlib.sha256(dest.read_bytes()).hexdigest()


def test_fetch_rejects_and_does_not_cache_error_body(tmp_path, monkeypatch):
    monkeypatch.setenv("BEA_API_KEY", "SUPER-SECRET-KEY")
    manifest = tmp_path / "manifest.csv"
    body = _echoing_body("SUPER-SECRET-KEY", error={"APIErrorCode": "1", "APIErrorDescription": "bad"})
    cfg = {**CFG, "bea": {**CFG["bea"], "api_min_interval_s": 0}}
    dest_path = tmp_path / f"{CFG['bea']['fixed_assets']['table']}.json"
    with pytest.raises(RuntimeError):
        fetch_fixed_assets(cfg, raw=tmp_path, client=_client(body), manifest=manifest)
    assert not dest_path.exists()
    assert not manifest.exists()
