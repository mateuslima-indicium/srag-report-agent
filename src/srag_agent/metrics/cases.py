"""Case growth rate: cases in the last N days versus the N days before."""

from __future__ import annotations

from datetime import date

import duckdb

from srag_agent.metrics.base import (
    PRELIMINARY_DAYS,
    Window,
    count_cases,
    latest_case_date,
    preliminary_cutoff,
    previous_window,
    ratio,
    uf_suffix,
    window_ending,
)
from srag_agent.metrics.models import MetricResult, pt_percent


def _growth(
    con: duckdb.DuckDBPyConnection, current: Window, uf: str | None
) -> tuple[int, int, float | None]:
    numerator = count_cases(con, current, uf)
    denominator = count_cases(con, previous_window(current), uf)
    share = ratio(numerator, denominator)
    return numerator, denominator, None if share is None else share - 1


def case_growth(
    con: duckdb.DuckDBPyConnection,
    reference_date: date,
    window_days: int,
    uf: str | None = None,
) -> MetricResult:
    """`(cases in the last N days / cases in the previous N days) - 1`, by symptom onset.

    Because the most recent days are under-reported, when the window reaches past the
    preliminary cutoff `extra` also carries the same ratio computed on windows that end at
    the cutoff ("consolidated" growth). Retroactive reference dates are consolidated already,
    so they carry neither the extra value nor the lag warning.
    """
    current = window_ending(reference_date, window_days)
    previous = previous_window(current)
    numerator, denominator, value = _growth(con, current, uf)

    latest = latest_case_date(con)
    cutoff = preliminary_cutoff(con)
    affected_by_lag = reference_date > cutoff
    extra: dict[str, float | int] = {}
    if affected_by_lag:
        consolidated = window_ending(cutoff, window_days)
        c_numerator, c_denominator, c_value = _growth(con, consolidated, uf)
        extra = {
            "consolidated_numerator": c_numerator,
            "consolidated_denominator": c_denominator,
        }
        if c_value is not None:
            extra["consolidated_value"] = round(c_value, 4)
        lag_caveats = [
            f"Os últimos {PRELIMINARY_DAYS} dias antes de {latest:%d/%m/%Y} são preliminares: "
            "o atraso de notificação faz o período recente parecer uma queda.",
            (
                f"Sobre dados consolidados (janela de {window_days} dias terminando em "
                f"{consolidated.end:%d/%m/%Y}: {c_numerator} casos contra {c_denominator} na "
                f"janela anterior) a variação é "
                + ("indefinida." if c_value is None else f"{pt_percent(c_value, signed=True)}.")
            ),
        ]
    else:
        lag_caveats = [
            f"A janela termina em {current.end:%d/%m/%Y}, antes do corte preliminar "
            f"({cutoff:%d/%m/%Y}): dados consolidados, sem efeito relevante do atraso de "
            "notificação."
        ]

    return MetricResult(
        name=f"case_growth_{window_days}d",
        label=f"Taxa de aumento de casos ({window_days} dias)",
        value=value,
        unit="percent_change",
        numerator=numerator,
        denominator=denominator,
        window_start=current.start,
        window_end=current.end,
        reference_date=reference_date,
        uf=uf,
        definition=(
            f"Casos de SRAG com primeiros sintomas entre {current.start:%d/%m/%Y} e "
            f"{current.end:%d/%m/%Y} ({numerator}) divididos pelos casos entre "
            f"{previous.start:%d/%m/%Y} e {previous.end:%d/%m/%Y} ({denominator}), menos 1"
            f"{uf_suffix(uf)}."
        ),
        caveats=[
            *lag_caveats,
            "Contagem por data de primeiros sintomas, não por data de notificação.",
        ],
        extra=extra,
    )
