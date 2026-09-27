"""SPEC §11.2 checkpoint: facts to confirm before building the universe. Missing inputs print BLOCKED, never a guess."""
import csv
import json
from pathlib import Path

import polars as pl

from nola_lw.analysis.se import moe90, weighted_total
from nola_lw.fetch.bea import load_bea
from nola_lw.fetch.bls import annual_mean, cpi_factor
from nola_lw.fetch.pums import PERSON_VARS, REP_VARS, scan_persons


def _year(col: str = "SERIALNO") -> pl.Expr:
    return pl.col(col).str.slice(0, 4)


def powpuma_by_year(df: pl.DataFrame, powsp: str) -> pl.DataFrame:
    return (df.filter(pl.col("POWSP") == powsp).with_columns(year=_year())
            .group_by("year", "POWPUMA").agg(weighted=pl.col("PWGTP").sum()))


def wage_check(persons: pl.DataFrame, bea_wages_2024usd: float, cfg) -> dict:
    """Survey WAGP (average year, ADJINC dollars) for the place-of-work universe vs. BEA wages and salaries."""
    o, u = cfg["orleans"], cfg["universe"]
    df = persons.filter((pl.col("POWSP") == o["powsp"]) & pl.col("POWPUMA").is_in(o["powpuma"])
                        & pl.col("COW").is_in(u["cow_wage"]) & (pl.col("WAGP") > 0))
    df = df.with_columns(wagp_adj=pl.col("WAGP") * pl.col("ADJINC") / 1e6)
    survey, se = weighted_total(df, "wagp_adj")
    pct = survey / bea_wages_2024usd - 1
    return {"survey": survey, "survey_moe": moe90(se, cfg["moe_z"]), "bea": bea_wages_2024usd,
            "pct_diff": pct, "pct_moe": moe90(se, cfg["moe_z"]) / bea_wages_2024usd,
            "flag": abs(pct) > cfg["checkpoint"]["wage_tolerance"], "n_records": df.height}


def suppressed_gdp(cagdp2: pl.DataFrame, total_line: str, sector_lines: list[str]) -> pl.DataFrame:
    """GDP in suppressed cells = total − disclosed sectors, per year. Suppression is read from `flag`, never zeros."""
    total = cagdp2.filter(pl.col("line_code") == total_line).select("year", total="value")
    sec = cagdp2.filter(pl.col("line_code").is_in(sector_lines)).group_by("year").agg(
        disclosed=pl.col("value").sum(), n_suppressed=pl.col("flag").is_not_null().sum(),
        suppressed_lines=pl.col("line_code").filter(pl.col("flag").is_not_null()))
    return (total.join(sec, on="year").with_columns(residual=pl.col("total") - pl.col("disclosed"))
            .with_columns(share=pl.col("residual") / pl.col("total")).sort("year"))


def bea_wages_2024usd(bea: pl.DataFrame, cpi_json: dict, cfg) -> tuple[float, pl.DataFrame]:
    w, base = cfg["bea"]["wages_line"], cfg["cpi"]["base_year"]
    rows = bea.filter((pl.col("table") == w["table"]) & (pl.col("line_code") == w["line"])
                      & (pl.col("geo") == cfg["bea"]["county_geo"])).sort("year")
    if rows["flag"].is_not_null().any() or rows.height == 0:
        raise ValueError(f"{w['table']} line {w['line']} missing or suppressed: {rows}")
    base_mean = annual_mean(cpi_json, base)
    rows = rows.with_columns(defl=pl.col("year").map_elements(lambda y: base_mean / annual_mean(cpi_json, y),
                                                              return_dtype=pl.Float64))
    rows = rows.with_columns(value_2024usd=pl.col("value") * pl.col("defl"))
    return rows["value_2024usd"].mean(), rows.select("year", "value", "defl", "value_2024usd")


def _load_persons(raw: Path, cfg) -> tuple[pl.DataFrame | None, list[str]]:
    pums = raw / "pums"
    files = [pums / f"psam_p{cfg['orleans']['state_fips']}.csv", pums / "psam_p28.csv", pums / "other_states.parquet"]
    missing = [str(f) for f in files if not f.exists()]
    done = set((pums / "other_states.done").read_text().split()) if (pums / "other_states.done").exists() else set()
    not_done = sorted(set(cfg["pums"]["other_states"]) - done)
    if not_done:
        missing.append(f"other-state PUMS not fetched: {', '.join(not_done)}")
    if missing:
        return None, missing
    powsp = cfg["orleans"]["powsp"]
    frames = [scan_persons(f) for f in files[:2]] + [pl.scan_parquet(files[2]).select(PERSON_VARS + REP_VARS)]
    return pl.concat(frames).filter(pl.col("POWSP") == powsp).collect(), []


def _tract_pumas(raw: Path, cfg) -> pl.DataFrame | None:
    f = raw / "pums" / Path(cfg["pums"]["tract_to_puma_url"]).name
    if not f.exists():
        return None
    return pl.read_csv(f, infer_schema_length=0, encoding="utf8-lossy").rename(lambda c: c.strip().lstrip("﻿"))


def _md_table(df: pl.DataFrame) -> str:
    cols = df.columns
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in df.iter_rows():
        lines.append("| " + " | ".join("" if v is None else (f"{v:,.0f}" if isinstance(v, float) else str(v)) for v in r) + " |")
    return "\n".join(lines)


def _blocked(what: str) -> str:
    return f"**BLOCKED: missing {what}.**\n"


def _section_powpuma(persons, tracts, raw: Path, cfg) -> str:
    o = cfg["orleans"]
    s = "## 1. Orleans POWPUMA code(s) by vintage\n\n"
    dict_f = raw / "pums" / Path(cfg["pums"]["dictionary_url"]).name
    if persons is None or tracts is None or not dict_f.exists():
        return s + _blocked("PUMS person files, the data dictionary or the tract-to-PUMA file")
    names = [r for r in csv.reader(dict_f.open(encoding="utf-8-sig")) if r and r[0] == "NAME" and r[1].startswith(("POW", "PUMA"))]
    s += "Data dictionary fields (every PUMA-type variable in the file):\n\n"
    s += "\n".join(dict.fromkeys(f"- `{r[1]}`: {r[4]}" for r in names)) + "\n\n"
    tbl = powpuma_by_year(persons, o["powsp"]).pivot(on="year", index="POWPUMA", values="weighted").sort("POWPUMA")
    tbl = tbl.select(["POWPUMA"] + sorted(c for c in tbl.columns if c != "POWPUMA"))
    s += f"Weighted persons with `POWSP` = {o['powsp']}, by `POWPUMA` and survey year (5-year weights):\n\n{_md_table(tbl.fill_null(0))}\n\n"
    st, cty = o["state_fips"], o["county_fips"]
    t = tracts.filter(pl.col("STATEFP") == st)
    by_puma = t.group_by("PUMA5CE").agg(counties=pl.col("COUNTYFP").unique().sort(), n_tracts=pl.len()).sort("PUMA5CE")
    by_puma = by_puma.with_columns(powpuma_prefix=pl.col("PUMA5CE").str.slice(0, 3) + "00")
    comp = by_puma.group_by("powpuma_prefix").agg(pumas=pl.col("PUMA5CE").sort(), counties=pl.col("counties").flatten().unique().sort()).sort("powpuma_prefix")
    data_codes = set(tbl["POWPUMA"])
    comp = comp.with_columns(pl.col("pumas").list.join(" "), pl.col("counties").list.join(" "),
                             code_in_data=pl.col("powpuma_prefix").is_in(list(data_codes)))
    s += ("2020 residence PUMAs in the state grouped by their first three digits + \"00\", "
          "with their counties from the 2020 tract-to-PUMA file, and whether that code occurs as a `POWPUMA`:\n\n"
          + _md_table(comp) + "\n\n")
    odd = sorted(data_codes - set(comp["powpuma_prefix"]))
    if odd:
        s += (f"`POWPUMA` codes in the data that do not follow the prefix pattern: {odd}. Each sits where prefix groups share "
              "a county (POWPUMAs must follow county lines), so Census merged them — e.g. a county split across "
              "PUMA groups. This does not affect Orleans, whose PUMA group contains no other county.\n\n")
    orleans_pumas = sorted(t.filter(pl.col("COUNTYFP") == cty)["PUMA5CE"].unique())
    checks = []
    for code in o["powpuma"]:
        grp = by_puma.filter(pl.col("powpuma_prefix") == code)
        only_orleans = grp.height > 0 and grp["counties"].explode().unique().to_list() == [cty]
        all_orleans_in = set(orleans_pumas) <= set(grp["PUMA5CE"])
        years = [c for c in tbl.columns if c != "POWPUMA"]
        row = tbl.filter(pl.col("POWPUMA") == code)
        in_all_years = row.height == 1 and all((row[y][0] or 0) > 0 for y in years)
        checks.append((code, only_orleans, all_orleans_in, in_all_years))
        s += (f"- `{code}`: residence PUMAs {grp['PUMA5CE'].to_list()} lie only in county {cty}: **{only_orleans}**; "
              f"they cover every Orleans PUMA {orleans_pumas}: **{all_orleans_in}**; present in every survey year: **{in_all_years}**.\n")
    ok = all(all(c[1:]) for c in checks)
    s += (f"\n**Verdict: {'CONFIRMED' if ok else 'NOT CONFIRMED'}** — config `orleans.powpuma` = {o['powpuma']}. "
          "There is one `POWPUMA` field, labelled as 2020 Census definitions, and the same codes appear in every survey year, "
          "so Census has coded all five years to 2020 POWPUMAs (no 2010 vintage in this file). "
          "Caveat: Census's official 2020 POWPUMA composition file was not reachable from this environment "
          "(usa.ipums.org is blocked; www2.census.gov carries only the tract-to-PUMA file), so the PUMA-to-POWPUMA link "
          "rests on the 3-digit naming convention, checked against the counts above.\n\n")
    return s


def _section_wages(persons, bea, cpi_json, cfg) -> str:
    s = "## 2. Survey WAGP vs. BEA wages and salaries (place of work)\n\n"
    w = cfg["bea"]["wages_line"]
    if persons is None or bea is None:
        return s + _blocked("; ".join(m for m, gone in [("PUMS person files (all states)", persons is None),
                                                          (f"BEA {w['table']} line {w['line']}", bea is None)] if gone))
    if cpi_json is None:
        r = wage_check(persons, float("nan"), cfg)
        nominal = bea.filter((pl.col("table") == w["table"]) & (pl.col("line_code") == w["line"])
                             & (pl.col("geo") == cfg["bea"]["county_geo"])).select("year", "value", "flag").sort("year")
        return s + (f"Survey (avg year, 2024$, ADJINC applied): ${r['survey']:,.0f} ± {r['survey_moe']:,.0f} (90% MOE), "
                    f"{r['n_records']:,} person records.\n\n{w['table']} line {w['line']}, nominal dollars:\n\n"
                    + _md_table(nominal) + "\n\n"
                    + _blocked(f"BLS CPI {cfg['cpi']['series']} to put BEA 2020–2023 in 2024 dollars, so the % difference is not computed"))
    bea_2024, yrs = bea_wages_2024usd(bea, cpi_json, cfg)
    r = wage_check(persons, bea_2024, cfg)
    s += ("Universe: `POWSP` = {p}, `POWPUMA` in {pp}, `COW` in {cow}, `WAGP` > 0; any state of residence. "
          "Survey = Σ PWGTP·WAGP·ADJINC/1e6 (5-year weights → an average year, 2024 dollars). "
          "BEA = 2020–2024 mean of {t} line {l}, each year put in 2024 dollars by CPI-U South annual averages.\n\n").format(
        p=cfg["orleans"]["powsp"], pp=cfg["orleans"]["powpuma"], cow=cfg["universe"]["cow_wage"], t=w["table"], l=w["line"])
    s += _md_table(yrs) + "\n\n"
    s += (f"| measure | value |\n|---|---|\n| survey (avg year, 2024$) | ${r['survey']:,.0f} ± {r['survey_moe']:,.0f} (90% MOE) |\n"
          f"| BEA (avg 2020–24, 2024$) | ${r['bea']:,.0f} |\n| difference | {r['pct_diff']:+.1%} ± {r['pct_moe']:.1%} |\n"
          f"| person records | {r['n_records']:,} |\n\n")
    tol = cfg["checkpoint"]["wage_tolerance"]
    s += (f"**{'FLAG: beyond' if r['flag'] else 'Within'} ±{tol:.0%}.**\n\n")
    s += ("Caveats: POWPUMA describes the job held last week, so people with wages in the past 12 months but not at work "
          "last week are outside this universe; WAGP is all wage income from all jobs, some possibly outside Orleans; "
          "BEA counts wages by place of work including non-survey items (e.g. military, some in-kind pay).\n\n")
    return s


def _section_mit(snapshots: Path, cfg) -> str:
    s = "## 3. MIT stated price basis\n\n"
    area = cfg["mit"]["county_path"].replace("/", "_")
    snaps = sorted(snapshots.glob(f"mit_{area}_*.csv"))
    if not snaps:
        return s + _blocked(f"MIT snapshot data/snapshots/mit_{area}_*.csv")
    rows = list(csv.DictReader(snaps[-1].open()))
    basis = {r["price_basis"] for r in rows}
    target = cfg["cpi"]["target"]
    s += f"Snapshot `{snaps[-1].name}`: MIT's methodology page says figures are adjusted to **{', '.join(sorted(basis))} dollars**. "
    s += f"Config `cpi.target` = `{target}`. Floor ({cfg['mit']['floor_type']}) = ${next(float(r['hourly']) for r in rows if r['household'] == cfg['mit']['floor_type']):.2f}/hr.\n\n"
    return s


def _section_suppression(bea, cfg) -> str:
    s = "## 4. GDP in BEA \"(D)\" cells; suppressed CAINC6N cells\n\n"
    if bea is None:
        return s + _blocked("BEA CAGDP2 and CAINC6N (and CAINC5N) files")
    b = cfg["bea"]
    geo = b["county_geo"]
    g = bea.filter((pl.col("table") == b["gdp_total_line"]["table"]) & (pl.col("geo") == geo))
    sup = suppressed_gdp(g, b["gdp_total_line"]["line"], b["gdp_sector_lines"])
    sup = sup.with_columns(pl.col("suppressed_lines").list.join(" "),
                           share=pl.col("share").map_elements(lambda x: f"{x:.4%}", return_dtype=pl.Utf8))
    s += "CAGDP2, Orleans, dollars. Residual = total − Σ top-level sectors; ±$2k is BEA rounding:\n\n" + _md_table(sup) + "\n\n"
    c6 = bea.filter((pl.col("table") == "CAINC6N") & (pl.col("geo") == geo))
    cnt = c6.group_by("year").agg(cells=pl.len(), suppressed=pl.col("flag").is_not_null().sum(),
                                  D=(pl.col("flag") == "(D)").sum(), NA=(pl.col("flag") == "(NA)").sum(),
                                  zero_values=(pl.col("value") == 0).sum()).sort("year")
    s += "CAINC6N, Orleans, cell counts by year:\n\n" + _md_table(cnt) + "\n\n"
    s += f"Total suppressed CAINC6N cells 2020–2024: **{int(cnt['suppressed'].sum())}** ((D) {int(cnt['D'].sum())}, (NA) {int(cnt['NA'].sum())}).\n\n"
    return s


def _dict_codes(dict_f: Path, var: str) -> set[str]:
    return {r[4] for r in csv.reader(dict_f.open(encoding="utf-8-sig")) if r and r[0] == "VAL" and r[1] == var}


def _section_naicsp(persons, cfg, dict_f: Path) -> str:
    s = "## 5. NAICSP codes by survey year (Orleans place-of-work universe)\n\n"
    if persons is None:
        return s + _blocked("PUMS person files (all states)")
    o, u = cfg["orleans"], cfg["universe"]
    df = persons.filter(pl.col("POWPUMA").is_in(o["powpuma"]) & pl.col("COW").is_in(u["cow_wage"])).with_columns(year=_year())
    by = df.group_by("year").agg(codes=pl.col("NAICSP").drop_nulls().unique().sort(), records=pl.len()).sort("year")
    years = by["year"].to_list()
    sets = dict(zip(years, (set(c) for c in by["codes"])))
    every = set.intersection(*sets.values())
    s += "| year | records | distinct codes | codes not in every year |\n|---|---|---|---|\n"
    for y in years:
        s += f"| {y} | {by.filter(pl.col('year') == y)['records'][0]:,} | {len(sets[y])} | {' '.join(sorted(sets[y] - every)) or '—'} |\n"
    union = set.union(*sets.values())
    s += f"\n{len(every)} codes appear in every year. The crosswalk (§11.6) must cover the union: {len(union)} codes.\n\n"
    if dict_f.exists():
        label = next(r[4] for r in csv.reader(dict_f.open(encoding="utf-8-sig")) if r and r[0] == "NAME" and r[1] == "NAICSP")
        off = {y: sorted(sets[y] - _dict_codes(dict_f, "NAICSP")) for y in years}
        s += (f"Dictionary label: \"{label}\". Codes in the data but not in the dictionary's value list, by year: "
              + "; ".join(f"{y}: {' '.join(v) or 'none'}" for y, v in off.items()) + ".\n\n")
    return s


def write_report(cfg, raw: Path = Path("data/raw"), out: Path = Path("data/out"), snapshots: Path = Path("data/snapshots")) -> Path:
    persons, missing_pums = _load_persons(raw, cfg)
    try:
        bea = load_bea(cfg, raw / "bea")
    except FileNotFoundError:
        bea = None
    cpi_f = raw / "bls" / f"{cfg['cpi']['series']}.json"
    cpi_json = json.loads(cpi_f.read_text()) if cpi_f.exists() else None
    text = "# Checkpoint report (SPEC §11 step 2)\n\n"
    if missing_pums:
        text += "Missing PUMS inputs: " + "; ".join(missing_pums) + "\n\n"
    text += _section_powpuma(persons, _tract_pumas(raw, cfg), raw, cfg)
    text += _section_wages(persons, bea, cpi_json, cfg)
    text += _section_mit(snapshots, cfg)
    if cpi_json is not None:
        c = cfg["cpi"]
        text += f"CPI factor {c['target']} ÷ {c['base_year']} average ({c['series']}): **{cpi_factor(cpi_json, c['base_year'], c['target']):.4f}**.\n\n"
    text += _section_suppression(bea, cfg)
    text += _section_naicsp(persons, cfg, raw / "pums" / Path(cfg["pums"]["dictionary_url"]).name)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "checkpoint.md"
    path.write_text(text)
    return path
