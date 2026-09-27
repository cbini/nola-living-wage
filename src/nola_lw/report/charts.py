"""SPEC §10.3: gap vs. GOS by industry (bar), and the hourly wage distribution with the floor marked."""
import math
import textwrap
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["text.parse_math"] = False  # labels carry literal "$"
import matplotlib.pyplot as plt  # noqa: E402
import polars as pl  # noqa: E402

# Reference palette (dataviz skill, light mode): slots 1-2, ink, grid.
SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
SERIES = ["#2a78d6", "#eb6834"]
OUT = Path("data/out")


def price_month(cfg) -> str:
    """cpi.target ("2025-12") as "December 2025"."""
    return datetime.strptime(cfg["cpi"]["target"], "%Y-%m").strftime("%B %Y")


def _years(cfg) -> str:
    y0, y1 = cfg["years"]["pool"]
    return f"{y0}–{y1}"


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, length=0)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def ratio_axis_max(capacity: pl.DataFrame) -> float:
    """x-axis limit (%) for gap_vs_gos: past the 100% fail line and past every bar, so none is clipped."""
    top = max((v for c in ("gap_gos", "gap_gos_low") for v in capacity[c] if v is not None), default=0.0)
    return max(105.0, 105.0 * top)


def gap_vs_gos(capacity: pl.DataFrame, labels: dict[str, str], cfg, out: Path = OUT) -> Path:
    """Horizontal bars: each industry's gap as % of its modeled GOS, upper and lower bound. A bar
    past 100% fails self-funding. Industries failing on GOS ≤ 0 sit on top, suppressed ones at the
    bottom, each labeled in words. The government line is left out: it is excluded from the test."""
    gov = cfg["crosswalk"]["gov_line"]
    df = (capacity.filter(pl.col("line").is_in(list(labels)) & (pl.col("line") != gov))
          .with_columns(label=pl.col("line").replace_strict(labels).map_elements(
              lambda t: textwrap.fill(t, 42), return_dtype=pl.Utf8),
              _key=pl.when(pl.col("gos") <= 0).then(pl.lit(float("inf")))
                     .when(pl.col("self_funding_low") == "fail").then(pl.lit(1e9))
                     .otherwise(pl.col("gap_gos").fill_null(-1.0)))
          .sort("_key"))
    fig, ax = plt.subplots(figsize=(10, 0.5 * df.height + 1.8), facecolor=SURFACE)
    _style(ax)
    h = 0.36
    y = range(df.height)
    for i, (col, gos_col, name) in enumerate([("gap_gos", "gos", "Upper bound GOS"),
                                              ("gap_gos_low", "gos_low", "Lower bound GOS (less depreciation)")]):
        pos = [k + (h / 2 if i == 0 else -h / 2) for k in y]
        ax.barh(pos, [(v or 0) * 100 for v in df[col]], height=h * 0.9, color=SERIES[i], label=name)
        for p, v, g, gap in zip(pos, df[col], df[gos_col], df["gap"]):
            note = ("suppressed" if g is None else "no sample" if gap is None else
                    f"{'upper' if i == 0 else 'lower'} GOS ≤ 0: fails" if g <= 0 else f"{v:.0%}" if v == 0 else None)
            if note:
                ax.text(1, p, note, va="center", fontsize=8, color=INK2)
    ax.axvline(100, color=INK, linewidth=1)
    ax.text(99, df.height - 0.5, "gap = GOS: fails beyond ", fontsize=8, color=INK, va="bottom", ha="right")
    ax.set_yticks(list(y), df["label"].to_list(), fontsize=8, color=INK)
    ax.set_xlim(0, ratio_axis_max(df))
    ax.set_xlabel("Employer cost of the floor gap (with payroll taxes) as % of the industry's modeled GOS", color=INK2)
    ax.legend(loc="lower right", frameon=False, fontsize=8, labelcolor=INK2)
    fig.suptitle(f"Employer cost of the floor gap vs. modeled GOS, by industry ({_years(cfg)} average)", x=0.01, ha="left", color=INK)
    fig.tight_layout()
    path = out / "gap_vs_gos.png"
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return path


def wage_distribution(u: pl.DataFrame, floor: float, cfg, out: Path = OUT) -> Path:
    """Weighted (PWGTP) histogram of hourly wages, with the floor marked. The x-axis stops at the
    weighted `report.hist_max_quantile`; the share above it is noted on the chart."""
    r = cfg["report"]
    s = u.sort("wage_hr")
    cum = s["PWGTP"].cum_sum() / s["PWGTP"].sum()
    xmax = s.filter(cum >= r["hist_max_quantile"])["wage_hr"][0]
    shown = s.filter(pl.col("wage_hr") <= xmax)
    bw = r["hist_bin_usd"]
    start = floor - math.ceil(floor / bw) * bw  # edges anchored at the floor: no bin mixes below and above
    bins = [start + k * bw for k in range(math.ceil((xmax - start) / bw) + 2)]
    fig, ax = plt.subplots(figsize=(10, 4.5), facecolor=SURFACE)
    _style(ax)
    ax.grid(axis="x", visible=False)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.hist(shown["wage_hr"], bins=bins, weights=shown["PWGTP"], color=SERIES[0], rwidth=0.85)
    ax.axvline(floor, color=INK, linewidth=1.2)
    ax.set_ylim(0, ax.get_ylim()[1] * 1.08)  # headroom so the floor label clears the bars
    ax.text(floor, ax.get_ylim()[1] * 0.97, f"floor ${floor:.2f}/hr  ", color=INK, va="top", ha="right", fontsize=9)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_xlabel(f"Hourly wage ({price_month(cfg)} dollars), ${r['hist_bin_usd']} bins with an edge at the floor; "
                  f"top {1 - r['hist_max_quantile']:.0%} of workers (above ${xmax:.0f}) not shown", color=INK2)
    ax.set_ylabel("Workers (average year)", color=INK2)
    ax.set_title(f"Hourly wages of people who work in Orleans Parish ({_years(cfg)})", loc="left", color=INK)
    fig.tight_layout()
    path = out / "wage_distribution.png"
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return path
