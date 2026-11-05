"""Metric, SQL and news tools on the synthetic database, with audit events."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from srag_agent.audit import AuditLogger
from srag_agent.data.db import open_readonly
from srag_agent.news.models import NewsBatch
from srag_agent.tools import build_tools
from tests.synthetic import build_synthetic_database


@pytest.fixture
def toolkit(tmp_path: Path):
    database = build_synthetic_database(tmp_path)
    audit = AuditLogger(tmp_path / "audit", run_id="test")
    with open_readonly(database) as con:
        tools = {t.name: t for t in build_tools(con, audit, NewsBatch, row_limit=5)}
        yield tools, audit


def test_tool_names_and_schemas(toolkit) -> None:
    tools, _ = toolkit
    assert set(tools) == {
        "get_case_growth",
        "get_mortality_rate",
        "get_icu_rate",
        "get_vaccination_rates",
        "get_daily_cases_series",
        "get_monthly_cases_series",
        "run_readonly_sql",
        "get_recent_news",
    }
    schema = tools["get_case_growth"].args_schema.model_json_schema()
    assert schema["properties"]["window_days"]["enum"] == [7, 30]


def test_metric_tool_returns_json_and_logs(toolkit) -> None:
    tools, audit = toolkit
    payload = json.loads(tools["get_case_growth"].invoke({"window_days": 7}))
    assert (payload["numerator"], payload["denominator"]) == (28, 21)
    rates = json.loads(tools["get_vaccination_rates"].invoke({}))
    assert [r["name"] for r in rates] == ["vaccination_covid", "vaccination_flu"]
    assert audit.count("tool_call", "get_case_growth") == 1
    assert audit.events[0].payload["args"]["reference_date"] == "2026-10-31"


def test_metric_tool_reports_invalid_arguments(toolkit) -> None:
    tools, _ = toolkit
    assert (
        tools["get_icu_rate"]
        .invoke({"uf": "SP", "reference_date": "2030-01-01"})
        .startswith("ERRO")
    )
    with pytest.raises(Exception, match="uf"):
        tools["get_icu_rate"].invoke({"uf": "XX"})


def test_sql_tool_executes_guarded_query_with_limit(toolkit) -> None:
    tools, audit = toolkit
    result = json.loads(
        tools["run_readonly_sql"].invoke(
            {
                "sql": "SELECT sg_uf_not, count(*) AS n FROM cases GROUP BY 1 ORDER BY 1",
                "purpose": "t",
            }
        )
    )
    assert result["columns"] == ["sg_uf_not", "n"]
    assert result["rows"] == [["MG", 60], ["RJ", 12], ["SP", 97]]
    big = json.loads(
        tools["run_readonly_sql"].invoke({"sql": "SELECT * FROM cases", "purpose": "t"})
    )
    assert len(big["rows"]) == 5
    assert audit.count("guardrail", "sql_guard") == 2
    assert all(e.payload["passed"] for e in audit.of_type("guardrail"))


def test_sql_tool_rejects_and_audits(toolkit) -> None:
    tools, audit = toolkit
    answer = tools["run_readonly_sql"].invoke({"sql": "DELETE FROM cases", "purpose": "x"})
    assert answer.startswith("CONSULTA REJEITADA")
    rejected = audit.of_type("guardrail")[-1]
    assert rejected.payload["passed"] is False
    assert "Apenas SELECT" in rejected.payload["reason"]
    error = tools["run_readonly_sql"].invoke({"sql": "SELECT nope FROM cases", "purpose": "x"})
    assert error.startswith("ERRO ao executar")


def test_news_tool_without_items(toolkit) -> None:
    tools, audit = toolkit
    assert tools["get_recent_news"].invoke({}).startswith("Sem notícias")
    assert audit.count("tool_call", "get_recent_news") == 1
