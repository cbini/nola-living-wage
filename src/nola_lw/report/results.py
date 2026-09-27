"""SPEC §10: results.md (headline + seven tables, each est ± 90% MOE with the subset window alongside),
one CSV per table, the two charts, and the QA log (qa.md). Every number comes from `ctx`."""
from pathlib import Path

import polars as pl

from nola_lw.report import charts

WINDOWS = ("pool", "subset")
DASH = "—"


# ---------- formatting ----------

class Fmt:
    def __init__(self, z: float):
        self.z = z

    def n(self, est, se=None) -> str:
        if est is None:
            return DASH
        s = f"{'−' if est < 0 else ''}{abs(est):,.0f}"
        return s if se is None else f"{s} ± {self.z * se:,.0f}"

    def usd(self, est, se=None) -> str:
        """Millions of dollars."""
        if est is None:
            return DASH
        s = f"{'−' if est < 0 else ''}${abs(est) / 1e6:,.1f}M"
        return s if se is None else f"{s} ± ${self.z * se / 1e6:,.1f}M"

    def usd_plain(self, est, se=None, digits: int = 0) -> str:
        if est is None:
            return DASH
        s = f"${est:,.{digits}f}"
        return s if se is None else f"{s} ± ${self.z * se:,.{digits}f}"

    def pct(self, est, se=None) -> str:
        if est is None:
            return DASH
        return f"{est:.1%}" if se is None else f"{est:.1%} ± {self.z * se * 100:.1f} pp"

    def pp(self, est, se) -> str:
        """A difference of shares, in percentage points."""
        return f"{'−' if est < 0 else ''}{abs(est) * 100:.1f} pp ± {self.z * se * 100:.1f} pp"


def _years(w: dict) -> str:
    return f"{w['years'][0]}–{w['years'][1]}"


def _table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(["---"] + ["---:"] * (len(header) - 1)) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def _household_label(key: str) -> str:
    a, w, c = (int(part[1:]) for part in key.split("_"))
    adults = "1 adult" if a == 1 else ("2 adults, 1 working" if w == 1 else "2 adults, both working")
    return f"{adults}, {c} {'child' if c == 1 else 'children'}"


def _row(df: pl.DataFrame, col: str, val) -> dict | None:
    r = df.filter(pl.col(col) == val)
    return r.row(0, named=True) if r.height else None


# ---------- headline ----------

def _failures(capacity: pl.DataFrame, labels: dict) -> list[tuple[str, str]]:
    """[(line, "both" | "upper" | "lower")] for industry lines that fail either bound."""
    out = []
    for line in labels:
        r = _row(capacity, "line", line)
        if r is None:
            continue
        up, low = r["self_funding"] == "fail", r["self_funding_low"] == "fail"
        if up or low:
            out.append((line, "both" if up and low else ("upper" if up else "lower")))
    return out


def _join(items: list[str], conj: str = "and") -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + f" {conj} " + items[-1]


def _share(a, b):
    return None if a is None or not b else a / b


WINDOW_METRICS = {"below": "workers below the floor", "share_below": "the share below",
                  "total_gap": "the total gap"}


def headline(ctx: dict) -> tuple[str, list[str]]:
    """The headline paragraph and its footnotes."""
    cfg, f, labels = ctx["cfg"], Fmt(ctx["cfg"]["moe_z"]), ctx["labels"]
    z = cfg["moe_z"]
    p, s = ctx["windows"]["pool"], ctx["windows"]["subset"]
    ps, ss = p["summary"], s["summary"]
    cap = p["capacity"]
    tot = _row(cap, "line", "total")
    gt = p["gos_tests"]
    notes: list[str] = []

    text = (f"In {_years(p)} (an average year), {f.n(*ps['below'])} of the {f.n(*ps['workers'])} wage and salary "
            f"workers whose job is in Orleans Parish ({f.pct(*ps['share_below'])}) earned less than the MIT living-wage "
            f"floor ({_household_label(cfg['mit']['floor_type'])}), ${ctx['floor']:.2f} an hour in {charts.price_month(cfg)} dollars. "
            f"Raising each of them to that floor for the hours they actually work would cost {f.usd(*ps['total_gap'])} "
            f"a year. That is {f.pct(tot['gap_gdp'], tot['gap_gdp_se'])} of Orleans GDP, "
            f"{f.pct(tot['gap_comp'], tot['gap_comp_se'])} of employee compensation and "
            f"{f.pct(tot['gap_wages'], tot['gap_wages_se'])} of wage and salary disbursements. "
            f"Against modeled gross operating surplus (GOS, upper bound; lower bound nets out depreciation): "
            f"(a) the private and nonprofit gap is {f.pct(*gt['private_upper'])} of private-industry GOS "
            f"({f.pct(*gt['private_lower'])} at the lower bound), and (b) the all-sector gap is "
            f"{f.pct(*gt['total_upper'])} of total GOS ({f.pct(*gt['total_lower'])} at the lower bound). "
            f"Excluding {labels[cfg['capacity']['imputed_rent_line']].lower()}, whose GOS includes imputed rent on "
            f"owner-occupied housing, (b) is {f.pct(*gt['total_upper_ex'])} ({f.pct(*gt['total_lower_ex'])} at the "
            f"lower bound). "
            f"The government workers' gap would be a {f.pct(*gt['government'])} raise to government compensation. ")

    fails = _failures(cap, labels)
    if fails:
        items = []
        neg_low = []
        for line, bound in fails:
            r = _row(cap, "line", line)
            mark = ""
            if bound in ("both", "upper") and r["gos"] is not None and r["gos"] <= 0:
                notes.append(f"[^gos-{line}]: Modeled upper-bound GOS for {labels[line]} is negative "
                             f"({f.usd(r['gos'])} a year): the method subtracts Louisiana's ratio of taxes on production "
                             f"less subsidies to GDP for this line ({r['tax_ratio']:.0%}) from an Orleans line whose "
                             f"compensation is already {r['comp'] / r['gdp']:.0%} of its GDP. It is reported as a "
                             f"failure under the SPEC §6 method. {cfg['report']['line_notes'].get(line, '')}".rstrip())
                mark += f"[^gos-{line}]"
            if bound in ("both", "lower") and r["gos_low"] is not None and r["gos_low"] <= 0:
                neg_low.append(line)
                mark += "[^gos-low]"
            which = {"both": "both bounds", "upper": "upper bound only", "lower": "lower bound only"}[bound]
            items.append(f"{labels[line]} ({which}){mark}")
        text += (f"By the self-funding test (an industry fails when its gap exceeds its own GOS), "
                 f"{len(fails)} {'industry fails' if len(fails) == 1 else 'industries fail'}: {_join(items)}. ")
        if neg_low:
            gaps = "; ".join(f"{labels[ln]} gap {f.usd(_row(cap, 'line', ln)['gap'])}" for ln in neg_low)
            notes.append(f"[^gos-low]: Modeled lower-bound GOS is ≤ 0 for {_join([labels[ln] for ln in neg_low])} "
                         f"(the national consumption-of-fixed-capital share applied to county GDP leaves nothing), so the "
                         f"lower-bound model gives no capacity there and a lower-bound \"fail\" says nothing about pay ({gaps}).")
    else:
        text += "No industry's gap exceeds its own GOS at either bound. "
    for line in cfg["report"]["spec_expected_fail"]:
        r = _row(cap, "line", line)
        if r is not None and r["self_funding"] == "pass" and r["self_funding_low"] == "pass":
            text += (f"{labels[line]}, which SPEC §6 expected to fail, passes both bounds: its gap is "
                     f"{f.pct(r['gap_gos'], r['gap_gos_se'])} of its upper-bound GOS and "
                     f"{f.pct(r['gap_gos_low'], r['gap_gos_low_se'])} of its lower bound. ")
    supp = [labels[ln] for ln in labels if (r := _row(cap, "line", ln)) and r["self_funding"] == "suppressed"]
    if supp:
        text += f"{_join(supp)} cannot be tested because BEA suppresses a needed cell. "
    sfails = _failures(s["capacity"], labels)
    text += (f"The same industries fail on {_years(s)} averages. " if sfails == fails else
             f"On {_years(s)} averages the failing set changes to: "
             f"{_join([f'{labels[ln]} ({b})' for ln, b in sfails]) if sfails else 'none'}. ")

    wd = ctx["window_diff"]
    fmt = {"below": f.n, "share_below": f.pp, "total_gap": f.usd}
    items = [f"{fmt[k](d, se)} {'in ' if k != 'below' else ''}{name} ({'beyond' if hit else 'within'} its 90% MOE)"
             for k, name in WINDOW_METRICS.items() for d, se, hit in [wd[k]]]
    differ = [name for k, name in WINDOW_METRICS.items() if wd[k][2]]
    same = [name for k, name in WINDOW_METRICS.items() if not wd[k][2]]
    text += (f"The {_years(s)} window gives {f.n(*ss['below'])} workers below the floor and a {f.usd(*ss['total_gap'])} "
             f"gap. Paired on the same replicate weights (the windows share data), {_years(p)} minus {_years(s)} is "
             f"{_join(items)}, so the windows ")
    text += (f"differ on {_join(differ)} but not on {_join(same, 'or')}. " if differ and same else
             "differ on all three. " if differ else "do not differ beyond their MOEs on any of the three. ")

    sb = ctx["survey_bea"]
    if sb["pct"] < 0:
        text += (f"Survey-reported wages for this universe fall {abs(sb['pct']):.1%} short of BEA wage and salary "
                 f"disbursements ({abs(sb['pct_like']):.1%} short like-for-like, counting salaries that owners of "
                 f"incorporated businesses pay themselves, as BEA does); to the extent the survey under-reports pay, "
                 f"the gap is overstated. ")
    else:
        text += (f"Survey-reported wages for this universe exceed BEA wage and salary disbursements by {sb['pct']:.1%} "
                 f"({sb['pct_like']:.1%} like-for-like). ")

    sens = ctx["sensitivities"]
    hr, hl = _row(sens, "sensitivity", "hours_rule"), _row(sens, "sensitivity", "headline")
    diff, moe = hr["total_gap"] - hl["total_gap"], z * hl["total_gap_se"]
    text += (f"Measured instead as annual earnings against the floor × {cfg['mit']['hours_full_time']:,} hours, the gap is "
             f"{f.usd(hr['total_gap'], hr['total_gap_se'])}, {f.usd(abs(diff))} {'above' if diff > 0 else 'below'} "
             f"the headline: " + (f"{abs(diff) / moe:.1f} times the headline's MOE." if abs(diff) > moe
                                  else "within the headline's MOE."))
    return text, notes


# ---------- tables ----------

def _two(fn, p: dict, s: dict, key: str) -> list[str]:
    return [fn(*p[key]), fn(*s[key])]


def _tables(ctx: dict) -> str:
    cfg, f, labels = ctx["cfg"], Fmt(ctx["cfg"]["moe_z"]), ctx["labels"]
    p, s = ctx["windows"]["pool"], ctx["windows"]["subset"]
    yp, ys = _years(p), _years(s)
    out = []

    # 1. workers below
    out.append("## 1. Workers below the floor\n")
    out.append(_table(["Measure", yp, ys], [
        ["Wage and salary workers", *_two(f.n, p["summary"], s["summary"], "workers")],
        ["Below the floor", *_two(f.n, p["summary"], s["summary"], "below")],
        ["Share below the floor", *_two(f.pct, p["summary"], s["summary"], "share_below")],
    ]))
    out.append("\nBy class of worker:\n")
    rows = []
    for cls in p["by_cow"]["cow_class"].to_list():
        a, b = _row(p["by_cow"], "cow_class", cls), _row(s["by_cow"], "cow_class", cls)
        rows.append([cls, f.n(a["below"], a["below_se"]), f.n(b["below"], b["below_se"]) if b else "no sample",
                     f.pct(a["share_below"], a["share_below_se"]),
                     f.pct(b["share_below"], b["share_below_se"]) if b else "no sample"])
    out.append(_table(["Class of worker", f"Below {yp}", f"Below {ys}", f"Share {yp}", f"Share {ys}"], rows))

    # 2. total gap
    out.append("\n## 2. Total gap\n")
    out.append(_table(["Measure", yp, ys], [
        ["Total annual gap", *_two(f.usd, p["summary"], s["summary"], "total_gap")],
        ["Mean shortfall per affected worker, $/hr",
         *[f.usd_plain(*w["summary"]["mean_short_hr"], digits=2) for w in (p, s)]],
        ["Mean shortfall per affected worker, $/yr", *[f.usd_plain(*w["summary"]["mean_short_yr"]) for w in (p, s)]],
    ]))
    out.append("\nBy class of worker:\n")
    rows = []
    for cls in p["by_cow"]["cow_class"].to_list():
        a, b = _row(p["by_cow"], "cow_class", cls), _row(s["by_cow"], "cow_class", cls)
        rows.append([cls, f.usd(a["total_gap"], a["total_gap_se"]),
                     f.usd(b["total_gap"], b["total_gap_se"]) if b else "no sample"])
    out.append(_table(["Class of worker", f"Gap {yp}", f"Gap {ys}"], rows))

    # 3. capacity ratios
    out.append("\n## 3. Gap vs. GDP, compensation and GOS\n")
    tp, ts = _row(p["capacity"], "line", "total"), _row(s["capacity"], "line", "total")

    rent_label = labels[cfg["capacity"]["imputed_rent_line"]]

    def rat(r, c):
        return f.pct(r[c], r[f"{c}_se"])
    rows = [["All-sector gap ÷ GDP", rat(tp, "gap_gdp"), rat(ts, "gap_gdp")],
            ["All-sector gap ÷ employee compensation", rat(tp, "gap_comp"), rat(ts, "gap_comp")],
            ["All-sector gap ÷ wage and salary disbursements", rat(tp, "gap_wages"), rat(ts, "gap_wages")]]
    for key, name in [("private_upper", "(a) Private + nonprofit gap ÷ private GOS, upper bound"),
                      ("private_lower", "(a) Private + nonprofit gap ÷ private GOS, lower bound"),
                      ("total_upper", "(b) All-sector gap ÷ total GOS, upper bound"),
                      ("total_lower", "(b) All-sector gap ÷ total GOS, lower bound"),
                      ("private_upper_ex", f"(a) excluding {rent_label}, upper bound"),
                      ("private_lower_ex", f"(a) excluding {rent_label}, lower bound"),
                      ("total_upper_ex", f"(b) excluding {rent_label}, upper bound"),
                      ("total_lower_ex", f"(b) excluding {rent_label}, lower bound"),
                      ("government", "Government gap ÷ government compensation")]:
        rows.append([name, *_two(f.pct, p["gos_tests"], s["gos_tests"], key)])
    out.append(_table(["Ratio", yp, ys], rows))
    out.append(f"\n\"Excluding {rent_label}\" removes that industry's gap from the numerator and its GOS from the "
               "denominator: its GOS includes imputed rent on owner-occupied housing.\n")
    out.append(f"\nBEA denominators (average year, {charts.price_month(cfg)} dollars; place of work):\n")
    pp, sp = _row(p["capacity"], "line", "private"), _row(s["capacity"], "line", "private")
    out.append(_table(["Measure", yp, ys], [
        ["GDP (CAGDP2)", f.usd(tp["gdp"]), f.usd(ts["gdp"])],
        ["Employee compensation (CAINC6N)", f.usd(tp["comp"]), f.usd(ts["comp"])],
        ["Wage and salary disbursements (CAINC5N)", f.usd(tp["wages"]), f.usd(ts["wages"])],
        ["Total GOS, upper / lower bound", f"{f.usd(tp['gos'])} / {f.usd(tp['gos_low'])}",
         f"{f.usd(ts['gos'])} / {f.usd(ts['gos_low'])}"],
        ["Private GOS, upper / lower bound", f"{f.usd(pp['gos'])} / {f.usd(pp['gos_low'])}",
         f"{f.usd(sp['gos'])} / {f.usd(sp['gos_low'])}"],
    ]))

    # 4. industries
    out.append("\n## 4. Industries and the self-funding test\n")
    out.append("An industry fails when its gap exceeds its own modeled GOS. The government line is excluded from "
               "the test (\"n/a\"; its BEA GOS is only depreciation) but its gap and gap ÷ compensation (payroll "
               "share) are shown.\n\n")
    rows = []
    for line, label in labels.items():
        a, b = _row(p["capacity"], "line", line), _row(s["capacity"], "line", line)
        ind = _row(p["by_industry"], "bea_line", line)
        gap_s = f.usd(b["gap"], b["gap_se"]) if b["gap"] is not None else "no sample"

        def cell(c, denom):
            if line == cfg["crosswalk"]["gov_line"] and denom != "comp":
                return "n/a"  # excluded from the GOS test
            return "no sample" if a["gap"] is None else rat(a, c) if a[denom] is not None else "suppressed"
        rows.append([label, f.n(ind["below"], ind["below_se"]) if ind else "no sample",
                     f.usd(a["gap"], a["gap_se"]) if a["gap"] is not None else "no sample", gap_s,
                     cell("gap_comp", "comp"), cell("gap_gos", "gos"), cell("gap_gos_low", "gos_low"),
                     f"{a['self_funding']} / {a['self_funding_low']}",
                     f"{b['self_funding']} / {b['self_funding_low']}"])
    out.append(_table(["Industry (CAGDP2)", f"Below {yp}", f"Gap {yp}", f"Gap {ys}", f"Gap ÷ comp {yp}",
                       f"Gap ÷ GOS upper {yp}", f"Gap ÷ GOS lower {yp}", f"Self-funding upper / lower {yp}",
                       f"Self-funding upper / lower {ys}"], rows))

    # 5. leakage
    out.append("\n## 5. Commuter leakage\n")
    out.append("Where below-floor workers and gap dollars live. Everyone stays in every gap and capacity figure; "
               "this only shows where a raise would be spent.\n\n")
    names = {"orleans": "Orleans Parish", "other_la": "Other Louisiana parishes", "out_of_state": "Out of state"}
    rows = []
    for res in p["leakage"]["residence"].to_list():
        a, b = _row(p["leakage"], "residence", res), _row(s["leakage"], "residence", res)
        rows.append([names.get(res, res), f.pct(a["share_workers"], a["share_workers_se"]),
                     f.pct(b["share_workers"], b["share_workers_se"]) if b else "no sample",
                     f.pct(a["share_gap"], a["share_gap_se"]),
                     f.pct(b["share_gap"], b["share_gap_se"]) if b else "no sample"])
    out.append(_table(["Residence", f"Below-floor workers {yp}", f"Below-floor workers {ys}",
                       f"Gap dollars {yp}", f"Gap dollars {ys}"], rows))

    # 6. households
    out.append("\n## 6. Household types (own MIT threshold)\n")
    out.append(f"Each worker against the Orleans MIT threshold for their own family unit. The annual columns compare "
               f"earnings with threshold × {cfg['mit']['hours_full_time']:,} hours (MIT's full-time basis), which "
               f"catches part-time and part-year workers who clear the hourly rate.\n\n")
    rows = []
    for key in p["households"]["household"].to_list():
        a, b = _row(p["households"], "household", key), _row(s["households"], "household", key)

        def g(r, c, fn):
            return fn(r[c], r[f"{c}_se"])
        rows.append([_household_label(key), f"${ctx['thresholds'][key]:.2f}", g(a, "workers", f.n),
                     g(a, "share_below_own", f.pct), g(b, "share_below_own", f.pct), g(a, "share_below_floor", f.pct),
                     g(a, "gap_own", f.usd), g(b, "gap_own", f.usd), g(a, "annual_share_below", f.pct),
                     g(a, "annual_gap", f.usd)])
    out.append(_table(["Household", "Threshold $/hr", f"Workers {yp}", f"Below own {yp}", f"Below own {ys}",
                       f"Below floor {yp}", f"Gap to own {yp}", f"Gap to own {ys}", f"Annual: below {yp}",
                       f"Annual: gap {yp}"], rows))

    # 7. sensitivities
    out.append("\n## 7. Sensitivities\n")
    out.append(f"All rows use {yp} unless the row says otherwise. \"Beyond MOE\" = the change from the headline "
               f"exceeds the headline's own 90% MOE on workers below or total gap; for years_2022_2024, the paired "
               f"window difference exceeds its own 90% MOE (as in the headline).\n\n")
    sens = ctx["sensitivities"]
    hl = _row(sens, "sensitivity", "headline")
    z = cfg["moe_z"]
    wd = ctx["window_diff"]
    rows = []
    for r in sens.iter_rows(named=True):
        beyond = (wd["below"][2] or wd["total_gap"][2] if r["sensitivity"] == "years_2022_2024" else
                  abs(r["workers_below"] - hl["workers_below"]) > z * hl["workers_below_se"]
                  or abs(r["total_gap"] - hl["total_gap"]) > z * hl["total_gap_se"])
        rows.append([r["sensitivity"], r["variant"], f"{r['factor']:.4f}", f.n(r["workers_below"], r["workers_below_se"]),
                     f.usd(r["total_gap"], r["total_gap_se"]), "yes" if beyond else "no"])
    out.append(_table(["Sensitivity", "Variant", "Threshold factor", "Workers below", "Total gap", "Beyond MOE"], rows))
    return "\n".join(out)


def _caveats(ctx: dict) -> str:
    cfg, sb, f = ctx["cfg"], ctx["survey_bea"], Fmt(ctx["cfg"]["moe_z"])
    rl = cfg["capacity"]["imputed_rent_line"]
    cap = ctx["windows"]["pool"]["capacity"]
    rent, priv, tot = (_row(cap, "line", ln) for ln in (rl, "private", "total"))
    return (
        "\n## Caveats\n\n"
        "- **Place of work.** Every worker measure counts jobs located in Orleans Parish, wherever the worker lives, "
        "to match BEA's place-of-work GDP and compensation. Residence enters only the leakage table, the "
        "Louisiana-residents-only sensitivity and the price pass-through allocator.\n"
        f"- **Full-time basis.** MIT thresholds assume {cfg['mit']['hours_full_time']:,} hours a year. The headline "
        "counts actual hours, so a part-time worker above the hourly floor can still fall far short in annual income; "
        "the hours-rule sensitivity (table 7; its effect is stated in the headline) and the annual household "
        "columns (table 6) show this.\n"
        "- **Tips and cash pay** are in `WAGP` only as reported, and are likely undercounted for accommodation and "
        "food services, which would overstate that industry's gap.\n"
        "- **GOS is modeled**, not published for counties: county GDP − compensation − GDP × Louisiana's net-tax "
        "ratio for the industry. The upper bound includes depreciation and proprietors' income, so it overstates "
        "distributable profit; the lower bound subtracts the national depreciation share by industry.\n"
        f"- **Real estate.** {ctx['labels'][rl]} (CAGDP2 line {rl}) is {f.pct(_share(rent['gos'], priv['gos']))} of "
        f"private and {f.pct(_share(rent['gos'], tot['gos']))} of total modeled GOS at the upper bound "
        f"({f.pct(_share(rent['gos_low'], priv['gos_low']))} and {f.pct(_share(rent['gos_low'], tot['gos_low']))} at "
        f"the lower bound, {_years(ctx['windows']['pool'])}); its GOS includes imputed rent on owner-occupied housing, "
        "which no employer can pay wages from, so this share cuts against the capacity argument (table 3 shows the "
        "GOS tests without it).\n"
        + (f"- **Survey vs. BEA.** Survey wages run {abs(sb['pct']):.1%} below BEA wage disbursements; if the survey "
           "under-reports pay, the gap is overstated." if sb["pct"] < 0 else
           f"- **Survey vs. BEA.** Survey wages run {sb['pct']:.1%} above BEA wage disbursements, so survey "
           "under-reporting is not evident in the total.")
        + " BEA also counts pay the survey universe misses (see checkpoint.md).\n"
        f"- **Dollars.** Wages and BEA values are in {charts.price_month(cfg)} dollars (MIT's price basis), converted by "
        f"CPI series {cfg['cpi']['series']}; BEA values year by year before averaging.\n"
        "- **MOEs** are 90% (replicate weights, successive-difference formula). Ratios' MOEs reflect survey error "
        "in the gap only; BEA totals are treated as fixed.\n"
    )


def results_md(ctx: dict) -> str:
    cfg = ctx["cfg"]
    head, notes = headline(ctx)
    return (
        "# Orleans Parish living-wage gap and capacity\n\n"
        f"Place of work, ACS PUMS {_years(ctx['windows']['pool'])} (average year) with "
        f"{_years(ctx['windows']['subset'])} alongside; MIT living wage snapshot; BEA county and state accounts. "
        f"Every estimate is ± 90% MOE. See SPEC.md for methods, qa.md for the QA log.\n\n"
        "## Headline\n\n" + head + "\n\n"
        f"Reading the tables: \"{DASH}\" means not defined[^dash]; \"suppressed\" means BEA withheld a needed cell; "
        "\"no sample\" means no survey workers in that group. No unknown value is printed as 0.\n\n"
        + _tables(ctx)
        + "\n## Charts\n\n![Floor gap vs. modeled GOS by industry](gap_vs_gos.png)\n\n"
        "![Distribution of hourly wages with the floor marked](wage_distribution.png)\n"
        + _caveats(ctx) + "\n"
        + "\n".join(notes + [f"[^dash]: A ratio whose denominator is ≤ 0 (e.g. negative modeled GOS), or a statistic "
                             f"for an empty household cell."]) + "\n"
    )


# ---------- CSVs ----------

def _with_moe(df: pl.DataFrame, z: float) -> pl.DataFrame:
    return df.with_columns([(pl.col(c) * z).alias(c[:-3] + "_moe") for c in df.columns if c.endswith("_se")])


def _long(d: dict, window: str) -> list[dict]:
    return [{"window": window, "measure": k, "est": v[0], "se": v[1]} for k, v in d.items()]


def write_csvs(ctx: dict, out: Path) -> list[Path]:
    z, w = ctx["cfg"]["moe_z"], ctx["windows"]
    labels = pl.DataFrame({"line": list(ctx["labels"]), "label": list(ctx["labels"].values())})

    def stack(key: str) -> pl.DataFrame:
        return pl.concat([w[n][key].with_columns(window=pl.lit(n)) for n in WINDOWS], how="diagonal_relaxed")

    tables = {
        "floor_summary": pl.DataFrame(_long(w["pool"]["summary"], "pool") + _long(w["subset"]["summary"], "subset")),
        "by_industry": stack("by_industry").join(labels, left_on="bea_line", right_on="line", how="left"),
        "by_cow_class": stack("by_cow"),
        "leakage": stack("leakage"),
        "households": stack("households"),
        "capacity": stack("capacity").join(labels, on="line", how="left"),
        "gos_tests": pl.DataFrame(_long(w["pool"]["gos_tests"], "pool") + _long(w["subset"]["gos_tests"], "subset"),
                                  schema={"window": pl.Utf8, "measure": pl.Utf8, "est": pl.Float64, "se": pl.Float64}),
        "sensitivities": ctx["sensitivities"],
    }
    paths = []
    for name, df in tables.items():
        if "se" in df.columns:
            df = df.with_columns(moe=pl.col("se") * z)
        path = out / f"{name}.csv"
        _with_moe(df, z).write_csv(path)
        paths.append(path)
    return paths


# ---------- QA ----------

def qa_md(ctx: dict) -> str:
    cfg, q, f = ctx["cfg"], ctx["qa"], Fmt(ctx["cfg"]["moe_z"])
    names = {"ms": "Mississippi residents", "other": "Other-state residents (not LA or MS)"}
    s = (f"# QA log\n\nQA only; not reported in results.md (SPEC §8). Window {_years(ctx['windows']['pool'])}, "
         "outliers dropped; ± 90% MOE.\n\n## Out-of-state residents in the universe\n\n")
    s += _table(["Group", "Records", "Workers", "Weighted wages (earnings)", "Below floor", "Gap"],
                [[names[r["src"]], f"{r['records']:,}", f.n(*r["workers"]), f.usd(*r["wages"]), f.n(*r["below"]),
                  f.usd(*r["gap"])] for r in q["by_src"]])
    n_out, (w_out, se_out) = q["outliers"]
    s += (f"\n## Outlier drops\n\nHourly wage < ${cfg['universe']['wage_min']} or > ${cfg['universe']['wage_max']}: "
          f"{n_out:,} records, {f.n(w_out, se_out)} weighted workers, dropped from every table except the "
          "outliers-included sensitivity.\n\n")
    s += (f"## Self-employed and unpaid family workers\n\nExcluded from the gap (SPEC §4), place of work Orleans: "
          f"{f.n(*q['self_employed'])} weighted.\n\n")
    c = q["crosswalk"]
    s += (f"## Crosswalk coverage\n\n{c['pairs_in_data']:,} distinct (COW, NAICSP) pairs in the universe (outliers "
          f"included), all mapped to exactly one BEA line ({c['crosswalk_rows']:,} crosswalk rows; `apply_crosswalk` "
          "raises on any missing or duplicate pair).\n\n")
    s += (f"## GOS method validation\n\nLouisiana: max |SAGDP2 − SAGDP4 − SAGDP3 − SAGDP7| over line 1 and the "
          f"{len(ctx['labels'])} industry lines, {_years(ctx['windows']['pool'])}: ${q['gos_resid']:,.0f} (tolerance "
          f"${cfg['capacity']['gos_validation_tol_usd']:,.0f}).\n\n")
    sup = q["suppressed"]
    s += "## Industry-years with suppressed BEA cells\n\n"
    s += (_table(["Line", "Industry", "Year", "GDP suppressed", "Compensation suppressed"],
                 [[r["line"], ctx["labels"][r["line"]], str(r["year"]), str(r["gdp_suppressed"]),
                   str(r["comp_suppressed"])] for r in sup.sort("line", "year").iter_rows(named=True)])
          if sup.height else "None.\n")
    n_c, (w_c, se_c) = q["children_over_cap"]
    s += (f"\n## Families with more than {cfg['households']['max_children']} children\n\n"
          f"Capped at {cfg['households']['max_children']} for MIT typing: {n_c:,} universe records, "
          f"{f.n(w_c, se_c)} weighted workers.\n")
    n_m, (w_m, se_m) = q["minors"]
    age = cfg["households"]["adult_age"]
    s += (f"\n## Workers under {age}\n\n{n_m:,} universe records, {f.n(w_m, se_m)} weighted workers. The MIT typing "
          f"(Decision 1) counts them as children in their parents' family unit, so table 6 compares them with that "
          f"family's threshold rather than a single adult's (the headline floor applies to everyone).\n")
    return s


def write_results(ctx: dict, out: Path = Path("data/out")) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    write_csvs(ctx, out)
    charts.gap_vs_gos(ctx["windows"]["pool"]["capacity"], ctx["labels"], ctx["cfg"], out)
    charts.wage_distribution(ctx["u"], ctx["floor"], ctx["cfg"], out)
    (out / "qa.md").write_text(qa_md(ctx))
    path = out / "results.md"
    path.write_text(results_md(ctx))
    return path
