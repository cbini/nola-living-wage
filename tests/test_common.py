import csv
import hashlib

import httpx
import pytest

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


def _failing_client():
    def handler(request):
        return httpx.Response(500, content=b"boom")
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_failed_download_leaves_no_part_file(tmp_path):
    dest = tmp_path / "x.csv"
    manifest = tmp_path / "manifest.csv"
    with pytest.raises(RuntimeError):
        download("https://example.test/x.csv", dest, client=_failing_client(), manifest=manifest)
    assert not dest.exists()
    assert not dest.with_name(dest.name + ".part").exists()


def test_error_message_redacts_key(tmp_path):
    manifest = tmp_path / "manifest.csv"
    with pytest.raises(RuntimeError) as excinfo:
        download("https://example.test/api", tmp_path / "a.json", params={"UserID": "SECRET"},
                  client=_failing_client(), manifest=manifest)
    assert "SECRET" not in str(excinfo.value)


def test_transform_applied_before_manifest_hash(tmp_path):
    """transform runs on the fetched bytes before the file is written, so the manifest's
    sha256 (and the file on disk) reflect the transformed content, never the raw response."""
    dest = tmp_path / "x.json"
    manifest = tmp_path / "manifest.csv"
    download("https://example.test/x.json", dest, client=_client([]), manifest=manifest,
              transform=lambda b: b.upper())
    assert dest.read_bytes() == BODY.upper()
    rows = list(csv.DictReader(manifest.open()))
    assert rows[0]["sha256"] == hashlib.sha256(BODY.upper()).hexdigest()


def test_transform_raising_leaves_no_file_or_manifest_row(tmp_path):
    """A validating transform (e.g. reject a broken 200 body) must stop the file from being
    durably cached and stop a manifest row from being written for it."""
    dest = tmp_path / "x.json"
    manifest = tmp_path / "manifest.csv"

    def reject(_b):
        raise RuntimeError("bad body")

    with pytest.raises(RuntimeError, match="bad body"):
        download("https://example.test/x.json", dest, client=_client([]), manifest=manifest, transform=reject)
    assert not dest.exists()
    assert not dest.with_name(dest.name + ".part").exists()
    assert not manifest.exists()


def test_error_message_includes_redacted_key(tmp_path):
    """The failed-request query string (params=) must still show up in the error, key redacted."""
    manifest = tmp_path / "manifest.csv"
    with pytest.raises(RuntimeError) as excinfo:
        download("https://example.test/api", tmp_path / "a.json", params={"UserID": "SECRET"},
                  client=_failing_client(), manifest=manifest)
    assert "UserID=REDACTED" in str(excinfo.value)
