"""MIT Living Wage Calculator scraper. Fails loudly on any layout change; never hardcodes values."""
import csv
import html as htmllib
import re
from datetime import date
from pathlib import Path

from nola_lw.fetch.common import download

HOUSEHOLD_KEYS = [f"a{a}_w{w}_c{c}" for a, w in [(1, 1), (2, 1), (2, 2)] for c in range(4)]
GROUP_HEADERS = ["1 ADULT", "2 ADULTS (1 WORKING)", "2 ADULTS (BOTH WORKING)"]
FIELDS = ["area", "household", "adults", "working", "children", "hourly", "price_basis", "fetched"]


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_thresholds(html: str) -> dict[str, float]:
    tables = re.findall(r'<table class="results_table.*?</table>', html, re.S)
    table = next((t for t in tables if re.search(r"<b>\s*Living Wage\s*</b>", t)), None)
    if table is None:
        raise ValueError("MIT page: no results table with a 'Living Wage' row")
    headers = [_text(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", table, re.S)]
    headers = [h.replace("( ", "(").replace(" )", ")") for h in headers if h]
    if headers != GROUP_HEADERS:
        raise ValueError(f"MIT page: household headers changed: {headers}")
    row = next(r for r in re.findall(r"<tr.*?</tr>", table, re.S) if "Living Wage" in r)
    values = [float(v.replace(",", "")) for v in re.findall(r"\$\s*([\d,]+\.\d{2})", row)]
    if len(values) != len(HOUSEHOLD_KEYS):
        raise ValueError(f"MIT page: expected {len(HOUSEHOLD_KEYS)} living-wage values, found {len(values)}")
    return dict(zip(HOUSEHOLD_KEYS, values))


def parse_price_basis(html: str) -> str:
    m = re.search(r"adjusted for inflation to\s+([A-Z][a-z]+\s+\d{4})\s+dollars", _text(html))
    if not m:
        raise ValueError("MIT methodology: stated price basis ('adjusted for inflation to <Month YYYY> dollars') not found")
    return m.group(1)


def _latest(snapshot_dir: Path, area: str) -> Path | None:
    found = sorted(snapshot_dir.glob(f"mit_{area}_*.csv"))
    return found[-1] if found else None


def scrape(cfg, snapshot_dir: Path = Path("data/snapshots"), refresh: bool = False) -> Path:
    """Returns the county snapshot CSV; the metro snapshot is written beside it."""
    m = cfg["mit"]
    areas = {m["county_path"].replace("/", "_"): m["county_path"], m["metro_path"].replace("/", "_"): m["metro_path"]}
    county = next(iter(areas))
    if not refresh and all(_latest(snapshot_dir, a) for a in areas):
        return _latest(snapshot_dir, county)
    today = date.today().isoformat()
    meth = download(f"{m['base_url']}/{m['methodology_path']}", snapshot_dir / f"mit_methodology_{today}.html", force=True)
    basis = parse_price_basis(meth.read_text())
    for area, path in areas.items():
        page = download(f"{m['base_url']}/{path}", snapshot_dir / f"mit_{area}_{today}.html", force=True)
        t = parse_thresholds(page.read_text())
        with (snapshot_dir / f"mit_{area}_{today}.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, FIELDS)
            w.writeheader()
            for k, v in t.items():
                a, wk, c = (int(x[1:]) for x in k.split("_"))
                w.writerow({"area": area, "household": k, "adults": a, "working": wk, "children": c,
                            "hourly": v, "price_basis": basis, "fetched": today})
    return snapshot_dir / f"mit_{county}_{today}.csv"
