import json
from pathlib import Path

import pytest

from nola_lw.fetch.bls import annual_mean, check_response, cpi_factor

FIX = json.loads((Path(__file__).parent / "fixtures" / "bls_cpi.json").read_text())


def test_cpi_factor_synthetic():
    # base-year months all 100, target month 105; the M13 annual row (999) must be ignored
    assert cpi_factor(FIX, 2024, "2025-12") == pytest.approx(1.05)


def test_annual_mean_ignores_m13():
    assert annual_mean(FIX, 2024) == pytest.approx(100.0)


def test_cpi_factor_missing_month():
    d = json.loads(json.dumps(FIX))
    d["Results"]["series"][0]["data"] = [r for r in d["Results"]["series"][0]["data"]
                                         if not (r["year"] == "2025" and r["period"] == "M12")]
    with pytest.raises(ValueError, match="2025-12"):
        cpi_factor(d, 2024, "2025-12")


def test_cpi_factor_incomplete_base_year():
    d = json.loads(json.dumps(FIX))
    d["Results"]["series"][0]["data"] = [r for r in d["Results"]["series"][0]["data"]
                                         if not (r["year"] == "2024" and r["period"] == "M07")]
    with pytest.raises(ValueError, match="2024"):
        cpi_factor(d, 2024, "2025-12")


def test_failed_request_is_fatal():
    with pytest.raises(RuntimeError, match="daily threshold"):
        check_response({"status": "REQUEST_NOT_PROCESSED", "message": ["daily threshold reached"], "Results": {}})
