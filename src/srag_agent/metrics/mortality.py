"""Case fatality among SRAG cases with a known outcome."""

from __future__ import annotations

from datetime import date

import duckdb

from srag_agent.metrics.base import (
    DEFAULT_WINDOW_DAYS,
    count_cases,
    ratio,
    uf_suffix,
    window_ending,
)
from srag_agent.metrics.models import MetricResult

DEATH = "evolucao = 2"
KNOWN_OUTCOME = "evolucao IN (1, 2, 3)"


def mortality_rate(
    con: duckdb.DuckDBPyConnection,
    reference_date: date,
    window_days: int = DEFAULT_WINDOW_DAYS,
    uf: str | None = None,
) -> MetricResult:
    """`EVOLUCAO = 2` over `EVOLUCAO in (1, 2, 3)` for cases with onset inside the window."""
    window = window_ending(reference_date, window_days)
    deaths = count_cases(con, window, uf, f" AND {DEATH}")
    known = count_cases(con, window, uf, f" AND {KNOWN_OUTCOME}")
    total = count_cases(con, window, uf)
    open_cases = total - known
    open_share = ratio(open_cases, total)
    return MetricResult(
        name="mortality_rate",
        label="Taxa de mortalidade (casos com desfecho conhecido)",
        value=ratio(deaths, known),
        unit="share",
        numerator=deaths,
        denominator=known,
        window_start=window.start,
        window_end=window.end,
        reference_date=reference_date,
        uf=uf,
        definition=(
            f"Óbitos por SRAG (EVOLUCAO=2, {deaths}) divididos pelos casos com desfecho "
            f"conhecido (cura, óbito por SRAG ou por outras causas, {known}) entre "
            f"{window.start:%d/%m/%Y} e {window.end:%d/%m/%Y}{uf_suffix(uf)}."
        ),
        caveats=[
            f"{open_cases} de {total} casos da janela ({(open_share or 0) * 100:.1f}%) ainda "
            "não têm desfecho registrado e ficaram fora do denominador; a mortalidade recente "
            "tende a ser revisada.",
            "Óbitos por outras causas (EVOLUCAO=3) contam no denominador, não no numerador.",
        ],
        extra={
            "total_cases": total,
            "open_cases": open_cases,
            "open_cases_share": round(open_share or 0.0, 4),
        },
    )
