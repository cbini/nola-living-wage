"""Download helper: every raw file gets a manifest row (url, date, sha256). Keys never hit disk."""
import csv
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

MANIFEST = Path("data/raw/manifest.csv")
FIELDS = ["url", "fetched_at_utc", "sha256", "bytes", "path"]
SECRET_PARAMS = {"key", "userid", "registrationkey"}


def redact(url: str) -> str:
    parts = urlsplit(url)
    q = [(k, "REDACTED" if k.lower() in SECRET_PARAMS else v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    return urlunsplit(parts._replace(query=urlencode(q)))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _last_hash(manifest: Path, dest: Path) -> str | None:
    if not manifest.exists():
        return None
    rows = [r for r in csv.DictReader(manifest.open()) if r["path"] == str(dest)]
    return rows[-1]["sha256"] if rows else None


def download(url: str, dest: Path, *, params: dict | None = None, client: httpx.Client | None = None,
             force: bool = False, manifest: Path = MANIFEST) -> Path:
    dest = Path(dest)
    if not force and dest.exists() and _last_hash(manifest, dest) == sha256(dest):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    own = client is None
    client = client or httpx.Client(timeout=300, follow_redirects=True)
    ok = False
    try:
        try:
            with client.stream("GET", url, params=params) as r:
                r.raise_for_status()
                full_url = str(r.request.url)
                with tmp.open("wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
            ok = True
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"GET {redact(url)} -> {e.response.status_code}") from None
    finally:
        if own:
            client.close()
        if not ok and tmp.exists():
            tmp.unlink()
    os.replace(tmp, dest)
    record(full_url, dest, manifest)
    return dest


def record(url: str, dest: Path, manifest: Path = MANIFEST) -> None:
    """Append a manifest row for a file already written to dest."""
    manifest.parent.mkdir(parents=True, exist_ok=True)
    new = not manifest.exists()
    with manifest.open("a", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        if new:
            w.writeheader()
        w.writerow({"url": redact(url), "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "sha256": sha256(dest), "bytes": dest.stat().st_size, "path": str(dest)})
