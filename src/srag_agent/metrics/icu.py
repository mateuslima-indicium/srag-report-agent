"""ICU admission share among hospitalised SRAG cases (proxy for ICU occupancy)."""

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

HOSPITALISED = "hospital = 1"


def icu_rate(
    con: duckdb.DuckDBPyConnection,
    reference_date: date,
    window_days: int = DEFAULT_WINDOW_DAYS,
    uf: str | None = None,
) -> MetricResult:
    """`UTI = 1` over `UTI in (1, 2)` among `HOSPITAL = 1` cases with onset in the window."""
    window = window_ending(reference_date, window_days)
    icu = count_cases(con, window, uf, f" AND {HOSPITALISED} AND uti = 1")
    known = count_cases(con, window, uf, f" AND {HOSPITALISED} AND uti IN (1, 2)")
    hospitalised = count_cases(con, window, uf, f" AND {HOSPITALISED}")
    return MetricResult(
        name="icu_rate",
        label="Taxa de ocupação de UTI (proxy: internados que foram para UTI)",
        value=ratio(icu, known),
        unit="share",
        numerator=icu,
        denominator=known,
        window_start=window.start,
        window_end=window.end,
        reference_date=reference_date,
        uf=uf,
        definition=(
            f"Internados por SRAG admitidos em UTI (UTI=1, {icu}) divididos pelos internados com "
            f"informação de UTI (UTI=1 ou 2, {known}) entre {window.start:%d/%m/%Y} e "
            f"{window.end:%d/%m/%Y}{uf_suffix(uf)}."
        ),
        caveats=[
            "Não é ocupação de leitos: o Sivep-Gripe não informa capacidade de UTI. "
            "A métrica é a proporção de internados por SRAG que precisaram de UTI.",
            f"{hospitalised - known} internados sem informação de UTI ficaram fora do denominador.",
        ],
        extra={"hospitalised_cases": hospitalised, "icu_unknown": hospitalised - known},
    )
