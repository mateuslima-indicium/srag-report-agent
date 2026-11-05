"""End-to-end graph runs with a scripted fake model (no network, no API key)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from langchain_core.messages import AIMessage

from srag_agent.agent.llm import build_chat_model
from srag_agent.agent.runner import run_report
from srag_agent.config import Settings
from srag_agent.news import google_news_rss
from srag_agent.report.models import MetricCommentary, NewsReference, ReportContent
from tests.conftest import FIXTURES_DIR
from tests.synthetic import REFERENCE_DATE, build_synthetic_database

RSS_FIXTURE = (FIXTURES_DIR / "google_news_srag.xml").read_bytes()
METRIC_NAMES = [
    "case_growth_7d",
    "case_growth_30d",
    "mortality_rate",
    "icu_rate",
    "vaccination_covid",
    "vaccination_flu",
]


def good_draft(news_ids: list[str] | None = None) -> ReportContent:
    """A draft that respects every rule: numbers below are the synthetic dataset's."""
    sections = [
        MetricCommentary(
            metric_name=name,
            headline=f"Leitura da métrica {name}",
            interpretation=(
                "Os casos recentes de SRAG são preliminares por atraso de notificação, "
                "e a mortalidade considera apenas casos com desfecho conhecido."
            ),
        )
        for name in METRIC_NAMES
    ]
    cited = [
        NewsReference(news_id=i, relevance="contextualiza a alta de casos") for i in news_ids or []
    ]
    context = " ".join(f"[{i}]" for i in news_ids or []) or "Sem notícias nesta execução."
    return ReportContent(
        executive_summary=(
            "Os casos de SRAG cresceram 61,7% nos últimos 30 dias (97 contra 60) com "
            "mortalidade de 11,8% entre os 85 casos com desfecho conhecido; os dados recentes "
            "são preliminares."
        ),
        metric_sections=sections,
        news_context=context,
        cited_news=cited,
        limitations=["Últimos 14 dias preliminares", "Vacinação é proxy entre pacientes"],
    )


@pytest.fixture
def synthetic_settings(settings: Settings) -> Settings:
    build_synthetic_database(settings.data_dir)
    return settings


def _run(settings: Settings, responses: list, **kwargs):
    model = build_chat_model(settings, fake_responses=responses)
    return run_report(settings, model=model, **kwargs)


@respx.mock
def test_full_run_with_tool_call_and_news(synthetic_settings: Settings) -> None:
    respx.get(url__startswith=google_news_rss.BASE_URL).mock(
        return_value=httpx.Response(200, content=RSS_FIXTURE)
    )
    responses = [
        AIMessage(
            content="Vou aprofundar por UF.",
            tool_calls=[
                {
                    "name": "run_readonly_sql",
                    "args": {
                        "sql": "SELECT sg_uf_not, count(*) AS n FROM cases GROUP BY 1",
                        "purpose": "recorte por UF",
                    },
                    "id": "call-1",
                },
                {"name": "get_mortality_rate", "args": {"window_days": 30}, "id": "call-2"},
            ],
        ),
        AIMessage(content="Achados: SP concentra 97 casos; mortalidade 11,8% (10/85)."),
        AIMessage(content=good_draft(["n1", "n2"]).model_dump_json()),
    ]
    result = _run(synthetic_settings, responses)

    assert result.validation is not None and result.validation.passed
    assert result.tool_calls_used == 2
    assert result.write_attempts == 1
    assert result.bundle.reference_date == REFERENCE_DATE
    text = result.report_path.read_text(encoding="utf-8")
    assert "# Relatório de SRAG: Brasil" in text
    assert "**+61,7%**" in text
    assert "**11,8%**" in text
    assert "[n1]" in text and "| n1 |" in text
    assert "## Como este relatório foi produzido" in text
    assert "`fake-chat-model`" in text
    assert "⚠️" not in text
    for chart in result.chart_paths:
        assert chart.exists()

    events = [
        json.loads(line) for line in result.audit_path.read_text(encoding="utf-8").splitlines()
    ]
    types = [e["type"] for e in events]
    assert types[0] == "run_start" and types[-1] == "run_end"
    assert events[-1]["payload"]["status"] == "ok"
    names = {(e["type"], e["name"]) for e in events}
    assert ("guardrail", "sql_guard") in names
    assert ("tool_call", "run_readonly_sql") in names
    assert ("tool_call", "get_mortality_rate") in names
    assert ("decision", "analyze") in names
    assert ("decision", "write_report") in names
    assert ("news_fetch", "google_news_rss") in names
    assert sum(1 for t in types if t == "llm_call") == 3


def test_invalid_draft_is_retried_then_marked_unverified(synthetic_settings: Settings) -> None:
    bad = good_draft().model_copy(
        update={"cited_news": [NewsReference(news_id="n9", relevance="x")]}
    )
    responses = [
        AIMessage(content="Sem aprofundamento."),
        AIMessage(content=bad.model_dump_json()),
        AIMessage(content="não é json"),
        AIMessage(content=bad.model_dump_json()),
    ]
    result = _run(synthetic_settings, responses, include_news=False)

    assert result.validation is not None and not result.validation.passed
    assert result.write_attempts == synthetic_settings.max_write_attempts == 3
    text = result.report_path.read_text(encoding="utf-8")
    assert "não verificados" in text
    assert "Citações de notícias inexistentes" in text
    assert "desativado por --no-news" in text
    events = [
        json.loads(line) for line in result.audit_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["payload"]["status"] == "unverified"
    assert any(e["name"] == "max_write_attempts" for e in events)
    assert any(e["type"] == "error" and e["name"] == "write_report" for e in events)


def test_tool_budget_is_enforced(synthetic_settings: Settings) -> None:
    tight = synthetic_settings.model_copy(update={"max_tool_calls": 1})
    responses = [
        AIMessage(
            content="duas chamadas",
            tool_calls=[
                {"name": "get_icu_rate", "args": {}, "id": "a"},
                {"name": "get_icu_rate", "args": {"window_days": 7}, "id": "b"},
            ],
        ),
        AIMessage(content="fim"),
        AIMessage(content=good_draft().model_dump_json()),
    ]
    result = _run(tight, responses, include_news=False, output_dir=tight.reports_dir / "x")
    assert result.tool_calls_used == 1
    events = [
        json.loads(line) for line in result.audit_path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(e["name"] == "tool_budget" and e["payload"]["passed"] is False for e in events)
    assert result.report_path.parent == tight.reports_dir / "x"


def test_uf_scoped_run(synthetic_settings: Settings, tmp_path: Path) -> None:
    responses = [AIMessage(content="ok"), AIMessage(content=good_draft().model_dump_json())]
    result = _run(synthetic_settings, responses, uf="sp", include_news=False)
    assert result.bundle.uf == "SP"
    assert result.report_path.name.endswith("-SP.md")
