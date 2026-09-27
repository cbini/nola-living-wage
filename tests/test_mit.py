from pathlib import Path

import pytest

from nola_lw.fetch.mit import HOUSEHOLD_KEYS, parse_price_basis, parse_thresholds

FIX = Path(__file__).parent / "fixtures"


def test_parse_orleans():
    t = parse_thresholds((FIX / "mit_22071.html").read_text())
    assert list(t) == HOUSEHOLD_KEYS
    assert t["a1_w1_c0"] == 20.29
    assert t["a2_w1_c0"] == 28.86
    assert t["a2_w2_c3"] == 28.45


def test_parse_rejects_layout_change():
    html = (FIX / "mit_22071.html").read_text().replace("$28.45", "", 1)
    with pytest.raises(ValueError):
        parse_thresholds(html)


def test_parse_rejects_reordered_headers():
    html = (FIX / "mit_22071.html").read_text().replace("1 ADULT", "ONE ADULT", 1)
    with pytest.raises(ValueError):
        parse_thresholds(html)


def test_price_basis():
    assert parse_price_basis((FIX / "mit_methodology.html").read_text()) == "December 2025"


def test_price_basis_missing():
    with pytest.raises(ValueError):
        parse_price_basis("<p>no basis here</p>")
