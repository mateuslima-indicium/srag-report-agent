"""Compute every metric and series in one deterministic pass."""

from __future__ import annotations

from datetime import date

import duckdb

from srag_agent.metrics.base import (
    GROWTH_WINDOWS,
    latest_case_date,
    resolve_reference_date,
    validate_uf,
)
from srag_agent.metrics.cases import case_growth
from srag_agent.metrics.icu import icu_rate
from srag_agent.metrics.models import MetricsBundle
from srag_agent.metrics.mortality import mortality_rate
from srag_agent.metrics.series import daily_cases, monthly_cases
from srag_agent.metrics.vaccination import covid_vaccination_rate, flu_vaccination_rate


def collect_metrics(
    con: duckdb.DuckDBPyConnection,
    reference_date: date | None = None,
    uf: str | None = None,
) -> MetricsBundle:
    """The four challenge metrics (growth at 7 and 30 days, mortality, ICU, vaccination x2)
    plus the two series, all for the same reference date and optional UF.
    """
    resolved_uf = validate_uf(uf)
    resolved_date = resolve_reference_date(con, reference_date)
    metrics = [
        *(case_growth(con, resolved_date, days, resolved_uf) for days in GROWTH_WINDOWS),
        mortality_rate(con, resolved_date, uf=resolved_uf),
        icu_rate(con, resolved_date, uf=resolved_uf),
        covid_vaccination_rate(con, resolved_date, uf=resolved_uf),
        flu_vaccination_rate(con, resolved_date, uf=resolved_uf),
    ]
    series = [
        daily_cases(con, resolved_date, resolved_uf),
        monthly_cases(con, resolved_date, resolved_uf),
    ]
    return MetricsBundle(
        reference_date=resolved_date,
        latest_case_date=latest_case_date(con),
        uf=resolved_uf,
        metrics=metrics,
        series=series,
    )
