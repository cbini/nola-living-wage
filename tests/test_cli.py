import pytest

from nola_lw import cli, fetch as fetch_pkg


def test_fetch_continues_past_failed_source(monkeypatch):
    ran = []

    class FakeBls:
        @staticmethod
        def fetch_cpi(cfg):
            ran.append("bls")
            raise RuntimeError("GET https://example.test/bls -> 500")

    class FakeBea:
        @staticmethod
        def fetch_zips(cfg):
            ran.append("bea")
            return ("a.zip",)

    class FakeMit:
        @staticmethod
        def scrape(cfg, refresh=False):
            ran.append("mit")
            return "mit.csv"

    class FakePums:
        @staticmethod
        def fetch_bulk(cfg):
            ran.append("pums")
            return ("p.csv",)

        @staticmethod
        def fetch_other_states(cfg):
            ran.append("pums_other")
            return "other.csv"

    monkeypatch.setattr(fetch_pkg, "bls", FakeBls, raising=False)
    monkeypatch.setattr(fetch_pkg, "bea", FakeBea, raising=False)
    monkeypatch.setattr(fetch_pkg, "mit", FakeMit, raising=False)
    monkeypatch.setattr(fetch_pkg, "pums", FakePums, raising=False)

    with pytest.raises(SystemExit) as excinfo:
        cli.fetch(cfg={}, only=None, refresh_mit=False)

    assert "bea" in ran
    assert "bls" in str(excinfo.value)
