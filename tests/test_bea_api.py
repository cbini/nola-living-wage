import json
from pathlib import Path

import pytest

from nola_lw.fetch.bea_api import parse_api

FIX = Path(__file__).parent / "fixtures" / "bea_api_fa.json"


def test_api_suppressed_zero_is_null():
    data = [{"TableName": "FAAt304ESI", "LineNumber": "1", "LineDescription": "x",
             "TimePeriod": "2020", "UNIT_MULT": "6", "DataValue": "0", "NoteRef": "(D)"}]
    df = parse_api(data)
    r = df.row(0, named=True)
    assert r["value"] is None
    assert r["flag"] == "(D)"


def test_api_literal_zero_stays_zero():
    data = [{"TableName": "FAAt304ESI", "LineNumber": "1", "LineDescription": "x",
             "TimePeriod": "2020", "UNIT_MULT": "6", "DataValue": "0", "NoteRef": ""}]
    df = parse_api(data)
    r = df.row(0, named=True)
    assert r["value"] == 0.0
    assert r["flag"] is None


def test_api_units_and_commas():
    data = [{"TableName": "FAAt304ESI", "LineNumber": "1", "LineDescription": "x",
             "TimePeriod": "2020", "UNIT_MULT": "6", "DataValue": "3,992,907", "NoteRef": ""}]
    df = parse_api(data)
    assert df.row(0, named=True)["value"] == 3_992_907 * 10**6


def test_api_error_is_fatal():
    from nola_lw.fetch.bea_api import check_for_error

    with pytest.raises(RuntimeError):
        check_for_error({"BEAAPI": {"Results": {"Error": {"APIErrorCode": "1", "APIErrorDescription": "bad"}}}})


def test_api_error_nested_is_fatal():
    from nola_lw.fetch.bea_api import check_for_error

    check_for_error({"BEAAPI": {"Results": {"Data": []}}})  # no Error key: fine
    with pytest.raises(RuntimeError):
        check_for_error({"BEAAPI": {"Request": {"Error": {"APIErrorCode": "2"}}}})


def test_fixture_has_fabricated_suppressed_cell():
    """The fixture is a trimmed REAL FAAt304ESI response, with one NoteRef "(D)" cell we
    fabricated by hand to exercise the suppression path (marked here, not left silent)."""
    data = json.loads(FIX.read_text())["BEAAPI"]["Results"]["Data"]
    df = parse_api(data)
    suppressed = df.filter(df["flag"] == "(D)")
    assert suppressed.height == 1  # fabricated cell
    assert suppressed.row(0, named=True)["value"] is None
