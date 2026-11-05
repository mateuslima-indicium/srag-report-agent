"""Metric values on the synthetic dataset are computed by hand in tests/synthetic.py."""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from srag_agent.data.db import open_readonly
from srag_agent.metrics import collect_metrics
from srag_agent.metrics.base import resolve_reference_date, validate_uf
from srag_agent.metrics.cases import case_growth
from srag_agent.metrics.series import daily_cases, monthly_cases
from tests.synthetic import PRELIMINARY_CUTOFF, REFERENCE_DATE, build_synthetic_database


@pytest.fixture(scope="module")
def con(tmp_path_factory: pytest.TempPathFactory) -> duckdb.DuckDBPyConnection:
    database = build_synthetic_database(tmp_path_factory.mktemp("synthetic"))
    with open_readonly(database) as connection:
        yield connection


def test_reference_date_defaults_to_latest_onset(con) -> None:
    assert resolve_reference_date(con, None) == REFERENCE_DATE
    assert resolve_reference_date(con, date(2026, 10, 1)) == date(2026, 10, 1)
    with pytest.raises(ValueError, match="posterior ao último caso"):
        resolve_reference_date(con, date(2026, 12, 1))


def test_uf_validation() -> None:
    assert validate_uf(" sp ") == "SP"
    assert validate_uf(None) is None
    with pytest.raises(ValueError, match="UF desconhecida"):
        validate_uf("XX")


def test_case_growth_windows(con) -> None:
    growth_30 = case_growth(con, REFERENCE_DATE, 30)
    assert (growth_30.numerator, growth_30.denominator) == (97, 60)
    assert growth_30.value == pytest.approx(97 / 60 - 1)
    assert growth_30.window_start == date(2026, 10, 2)
    growth_7 = case_growth(con, REFERENCE_DATE, 7)
    assert (growth_7.numerator, growth_7.denominator) == (28, 21)
    assert growth_7.value == pytest.approx(1 / 3)


def test_case_growth_reports_consolidated_value_only_when_lag_applies(con) -> None:
    recent = case_growth(con, REFERENCE_DATE, 7)
    assert recent.extra["consolidated_denominator"] == 21
    assert any("preliminares" in caveat for caveat in recent.caveats)
    retro = case_growth(con, PRELIMINARY_CUTOFF, 7)
    assert "consolidated_value" not in retro.extra
    assert any("antes do corte preliminar" in caveat for caveat in retro.caveats)


def test_case_growth_with_zero_denominator_is_none(con) -> None:
    growth = case_growth(con, REFERENCE_DATE, 30, uf="SP")
    assert growth.denominator == 0
    assert growth.value is None


def test_rates_match_hand_computed_values(con) -> None:
    bundle = collect_metrics(con)
    mortality = bundle.metric("mortality_rate")
    assert (mortality.numerator, mortality.denominator) == (10, 85)
    assert mortality.extra["open_cases"] == 12
    assert mortality.extra["total_cases"] == 97
    icu = bundle.metric("icu_rate")
    assert (icu.numerator, icu.denominator) == (20, 90)
    covid = bundle.metric("vaccination_covid")
    assert (covid.numerator, covid.denominator) == (30, 90)
    flu = bundle.metric("vaccination_flu")
    assert (flu.numerator, flu.denominator) == (40, 90)
    assert flu.extra["vaccine_unknown"] == 7
    assert all(metric.caveats for metric in bundle.metrics)
    assert {metric.name for metric in bundle.metrics} == {
        "case_growth_7d",
        "case_growth_30d",
        "mortality_rate",
        "icu_rate",
        "vaccination_covid",
        "vaccination_flu",
    }


def test_daily_series_is_zero_filled_and_flags_preliminary_tail(con) -> None:
    series = daily_cases(con, REFERENCE_DATE)
    assert len(series.points) == 30
    assert series.points[0].period == date(2026, 10, 2)
    assert series.total == 97
    assert series.preliminary_cutoff == PRELIMINARY_CUTOFF
    assert [p.preliminary for p in series.points].count(True) == 14
    sparse = daily_cases(con, date(2026, 8, 20), uf="RJ")
    assert sparse.total == 1
    assert sum(1 for p in sparse.points if p.cases == 0) == 29


def test_monthly_series_covers_twelve_complete_months(con) -> None:
    series = monthly_cases(con, REFERENCE_DATE, uf="RJ")
    assert [p.period for p in series.points][0] == date(2025, 10, 1)
    assert [p.period for p in series.points][-1] == date(2026, 9, 1)
    assert series.total == 11  # the 2025-09 case falls outside the 12-month window
    assert all(not p.preliminary for p in series.points)
    national = monthly_cases(con, REFERENCE_DATE)
    assert national.points[-1].cases == 58  # MG: 29 September days x 2 cases/day


def test_bundle_lookup_errors(con) -> None:
    bundle = collect_metrics(con, uf="sp")
    assert bundle.uf == "SP"
    with pytest.raises(KeyError):
        bundle.metric("nope")
    with pytest.raises(KeyError):
        bundle.get_series("nope")
