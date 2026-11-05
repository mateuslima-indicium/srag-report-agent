"""Daily (30 days) and monthly (12 complete months) case series."""

from __future__ import annotations

from datetime import date, timedelta

import duckdb

from srag_agent.data.db import CASES_TABLE, fetch_all
from srag_agent.metrics.base import (
    preliminary_cutoff,
    uf_clause,
    uf_suffix,
    window_ending,
)
from srag_agent.metrics.models import SeriesPoint, SeriesResult

DAILY_DAYS = 30
MONTHLY_MONTHS = 12


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _add_months(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def daily_cases(
    con: duckdb.DuckDBPyConnection, reference_date: date, uf: str | None = None
) -> SeriesResult:
    """Cases per symptom-onset day for the 30 days ending on `reference_date` (zero-filled)."""
    window = window_ending(reference_date, DAILY_DAYS)
    clause, params = uf_clause(uf)
    rows = fetch_all(
        con,
        f"SELECT dt_sin_pri AS period, count(*) AS cases FROM {CASES_TABLE} "
        f"WHERE dt_sin_pri BETWEEN ? AND ?{clause} GROUP BY 1",
        [window.start, window.end, *params],
    )
    counts = {row["period"]: int(row["cases"]) for row in rows}
    cutoff = preliminary_cutoff(con)
    points = [
        SeriesPoint(period=day, cases=counts.get(day, 0), preliminary=day > cutoff)
        for day in (window.start + timedelta(days=i) for i in range(DAILY_DAYS))
    ]
    return SeriesResult(
        name="daily_cases_30d",
        label="Casos diários de SRAG nos últimos 30 dias",
        granularity="daily",
        reference_date=reference_date,
        uf=uf,
        points=points,
        preliminary_cutoff=cutoff,
        definition=(
            f"Número de casos de SRAG por data de primeiros sintomas, de "
            f"{window.start:%d/%m/%Y} a {window.end:%d/%m/%Y}{uf_suffix(uf)}."
        ),
        caveats=[f"Dias após {cutoff:%d/%m/%Y} são preliminares (atraso de notificação)."],
    )


def monthly_cases(
    con: duckdb.DuckDBPyConnection, reference_date: date, uf: str | None = None
) -> SeriesResult:
    """Cases per month for the 12 complete months before the month of `reference_date`."""
    end_month = _month_start(reference_date)
    start_month = _add_months(end_month, -MONTHLY_MONTHS)
    clause, params = uf_clause(uf)
    rows = fetch_all(
        con,
        f"SELECT date_trunc('month', dt_sin_pri)::DATE AS period, count(*) AS cases "
        f"FROM {CASES_TABLE} WHERE dt_sin_pri >= ? AND dt_sin_pri < ?{clause} GROUP BY 1",
        [start_month, end_month, *params],
    )
    counts = {row["period"]: int(row["cases"]) for row in rows}
    cutoff = preliminary_cutoff(con)
    months = [_add_months(start_month, i) for i in range(MONTHLY_MONTHS)]
    points = [
        SeriesPoint(
            period=month,
            cases=counts.get(month, 0),
            preliminary=_add_months(month, 1) - timedelta(days=1) > cutoff,
        )
        for month in months
    ]
    last_month_end = end_month - timedelta(days=1)
    return SeriesResult(
        name="monthly_cases_12m",
        label="Casos mensais de SRAG nos últimos 12 meses completos",
        granularity="monthly",
        reference_date=reference_date,
        uf=uf,
        points=points,
        preliminary_cutoff=cutoff,
        definition=(
            f"Número de casos de SRAG por mês de primeiros sintomas, de {start_month:%m/%Y} a "
            f"{last_month_end:%m/%Y}{uf_suffix(uf)}; o mês de {reference_date:%m/%Y} fica de fora "
            "por estar incompleto."
        ),
        caveats=[
            f"Meses com dias após {cutoff:%d/%m/%Y} são preliminares (atraso de notificação)."
        ],
    )
