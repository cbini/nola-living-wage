import csv
import hashlib

import httpx

from nola_lw.fetch.common import download

BODY = b"hello,world\n1,2\n"


def _client(calls):
    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=BODY)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_download_writes_manifest_row(tmp_path):
    dest = tmp_path / "raw" / "x.csv"
    manifest = tmp_path / "raw" / "manifest.csv"
    download("https://example.test/x.csv", dest, client=_client([]), manifest=manifest)
    rows = list(csv.DictReader(manifest.open()))
    assert dest.read_bytes() == BODY
    assert rows[0]["sha256"] == hashlib.sha256(BODY).hexdigest()
    assert int(rows[0]["bytes"]) == len(BODY)
    assert rows[0]["url"] == "https://example.test/x.csv"


def test_manifest_redacts_keys(tmp_path):
    manifest = tmp_path / "manifest.csv"
    download("https://example.test/api?registrationkey=SECRET3", tmp_path / "a.json",
             params={"key": "SECRET", "UserID": "SECRET2"}, client=_client([]), manifest=manifest)
    assert "SECRET" not in manifest.read_text()


def test_skip_when_unchanged(tmp_path):
    calls = []
    manifest = tmp_path / "manifest.csv"
    dest = tmp_path / "x.csv"
    download("https://example.test/x.csv", dest, client=_client(calls), manifest=manifest)
    download("https://example.test/x.csv", dest, client=_client(calls), manifest=manifest)
    assert len(calls) == 1
