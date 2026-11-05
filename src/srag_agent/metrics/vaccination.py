"""Vaccination share among SRAG cases (proxy; not population coverage)."""

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

_POPULATION_CAVEAT = (
    "É a proporção de vacinados entre pacientes com SRAG, não a cobertura vacinal da "
    "população: o recorte é de casos graves e não representa a população geral. A cobertura "
    "populacional tem fonte própria (PNI/RNDS), fora do escopo deste dataset."
)


def _vaccination_metric(
    con: duckdb.DuckDBPyConnection,
    reference_date: date,
    window_days: int,
    uf: str | None,
    column: str,
    name: str,
    label: str,
    vaccine: str,
) -> MetricResult:
    window = window_ending(reference_date, window_days)
    vaccinated = count_cases(con, window, uf, f" AND {column} = 1")
    known = count_cases(con, window, uf, f" AND {column} IN (1, 2)")
    total = count_cases(con, window, uf)
    return MetricResult(
        name=name,
        label=label,
        value=ratio(vaccinated, known),
        unit="share",
        numerator=vaccinated,
        denominator=known,
        window_start=window.start,
        window_end=window.end,
        reference_date=reference_date,
        uf=uf,
        definition=(
            f"Casos de SRAG com {vaccine} registrada ({column.upper()}=1, {vaccinated}) "
            f"divididos pelos casos com informação vacinal ({column.upper()}=1 ou 2, {known}) "
            f"entre {window.start:%d/%m/%Y} e {window.end:%d/%m/%Y}{uf_suffix(uf)}."
        ),
        caveats=[
            _POPULATION_CAVEAT,
            f"{total - known} casos sem informação vacinal ficaram fora do denominador.",
        ],
        extra={"total_cases": total, "vaccine_unknown": total - known},
    )


def covid_vaccination_rate(
    con: duckdb.DuckDBPyConnection,
    reference_date: date,
    window_days: int = DEFAULT_WINDOW_DAYS,
    uf: str | None = None,
) -> MetricResult:
    """`VACINA_COV = 1` over `VACINA_COV in (1, 2)` for cases with onset in the window."""
    return _vaccination_metric(
        con,
        reference_date,
        window_days,
        uf,
        column="vacina_cov",
        name="vaccination_covid",
        label="Taxa de vacinação contra covid-19 entre casos de SRAG (proxy)",
        vaccine="vacina contra covid-19",
    )


def flu_vaccination_rate(
    con: duckdb.DuckDBPyConnection,
    reference_date: date,
    window_days: int = DEFAULT_WINDOW_DAYS,
    uf: str | None = None,
) -> MetricResult:
    """`VACINA = 1` over `VACINA in (1, 2)` for cases with onset in the window."""
    return _vaccination_metric(
        con,
        reference_date,
        window_days,
        uf,
        column="vacina",
        name="vaccination_flu",
        label="Taxa de vacinação contra gripe entre casos de SRAG (proxy)",
        vaccine="vacina contra gripe na última campanha",
    )
