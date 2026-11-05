"""The two report charts, rendered deterministically with matplotlib (never by the LLM)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from srag_agent.metrics.base import scope_label  # noqa: E402
from srag_agent.metrics.models import SeriesResult  # noqa: E402

WIDTH_PX, HEIGHT_PX, DPI = 1600, 900, 150
MARGINS = {"left": 0.08, "right": 0.97, "top": 0.84, "bottom": 0.14}
"""Figure margins; the left one leaves room for the y-label next to 5-digit ticks."""
SOURCE_NOTE = (
    "Fonte: Sivep-Gripe / Open DATASUS (SRAG 2019 a 2026), casos por data de primeiros sintomas."
)

# Palette: one series hue (blue), neutral ink for text, gray for preliminary marks.
SERIES_COLOR = "#2a78d6"
PRELIMINARY_COLOR = "#9a9893"
PRELIMINARY_BAND = "#e8e7e3"
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"

PT_MONTHS = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")


def _new_figure(title: str, subtitle: str) -> tuple[Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI), dpi=DPI)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=TEXT_SECONDARY, labelsize=9, length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: thousands(int(value))))
    ax.set_axisbelow(True)
    fig.text(0.06, 0.95, title, fontsize=15, fontweight="bold", color=TEXT_PRIMARY, ha="left")
    fig.text(0.06, 0.905, subtitle, fontsize=10, color=TEXT_SECONDARY, ha="left")
    fig.text(0.06, 0.03, SOURCE_NOTE, fontsize=8, color=TEXT_SECONDARY, ha="left")
    fig.subplots_adjust(**MARGINS)
    return fig, ax


def thousands(value: int) -> str:
    """Brazilian thousands separator: 12.345 (shared with the Markdown renderer)."""
    return f"{value:,}".replace(",", ".")


def _annotate_preliminary(ax: plt.Axes, text: str) -> None:
    ax.text(
        0.99,
        0.97,
        text,
        transform=ax.transAxes,
        fontsize=8.5,
        color=TEXT_SECONDARY,
        ha="right",
        va="top",
    )


def plot_daily_cases(series: SeriesResult, output: Path) -> Path:
    """Line chart of daily cases; the preliminary tail is shaded and drawn in gray."""
    fig, ax = _new_figure(
        f"Casos diários de SRAG, últimos 30 dias ({scope_label(series.uf)})",
        f"Até {series.reference_date:%d/%m/%Y}. Total no período: {thousands(series.total)} casos.",
    )
    dates = [point.period for point in series.points]
    values = [point.cases for point in series.points]
    firm = [point for point in series.points if not point.preliminary]
    preliminary = [point for point in series.points if point.preliminary]

    ax.plot(dates, values, color=SERIES_COLOR, linewidth=2, zorder=3)
    ax.scatter(
        [p.period for p in firm], [p.cases for p in firm], s=28, color=SERIES_COLOR, zorder=4
    )
    if preliminary:
        band_start = preliminary[0].period
        ax.axvspan(band_start, dates[-1], color=PRELIMINARY_BAND, zorder=1)
        ax.scatter(
            [p.period for p in preliminary],
            [p.cases for p in preliminary],
            s=28,
            color=PRELIMINARY_COLOR,
            zorder=4,
        )
        _annotate_preliminary(
            ax, f"Área cinza: dados preliminares (após {series.preliminary_cutoff:%d/%m/%Y})"
        )
    peak = max(series.points, key=lambda point: point.cases)
    ax.annotate(
        thousands(peak.cases),
        (peak.period, peak.cases),
        textcoords="offset points",
        xytext=(0, 8),
        ha="center",
        fontsize=9,
        color=TEXT_PRIMARY,
    )
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    ax.set_xlim(dates[0], dates[-1])
    ax.margins(x=0.02)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("casos por dia", color=TEXT_SECONDARY, fontsize=9)
    return _save(fig, output)


def plot_monthly_cases(series: SeriesResult, output: Path) -> Path:
    """Bar chart of monthly cases; preliminary months are drawn in gray."""
    fig, ax = _new_figure(
        f"Casos mensais de SRAG, últimos 12 meses ({scope_label(series.uf)})",
        f"Meses completos até {series.points[-1].period:%m/%Y}. "
        f"Total no período: {thousands(series.total)} casos.",
    )
    labels = [f"{PT_MONTHS[p.period.month - 1]}/{p.period:%y}" for p in series.points]
    colors = [PRELIMINARY_COLOR if p.preliminary else SERIES_COLOR for p in series.points]
    positions = range(len(series.points))
    bars = ax.bar(positions, [p.cases for p in series.points], color=colors, width=0.72, zorder=3)
    for bar, point in zip(bars, series.points, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            thousands(point.cases),
            ha="center",
            va="bottom",
            fontsize=8.5,
            color=TEXT_PRIMARY,
        )
    if any(p.preliminary for p in series.points):
        _annotate_preliminary(ax, "Barras cinza: meses com dados preliminares")
    ax.set_xticks(list(positions), labels)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("casos por mês", color=TEXT_SECONDARY, fontsize=9)
    return _save(fig, output)


def _save(fig: Figure, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=DPI, facecolor=SURFACE)
    plt.close(fig)
    return output
