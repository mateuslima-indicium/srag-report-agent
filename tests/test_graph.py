"""End-to-end graph runs with a scripted fake model (no network, no API key)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from langchain_core.messages import AIMessage

from srag_agent.agent.llm import build_chat_model
from srag_agent.agent.runner import RunResult, run_report
from srag_agent.config import Settings
from srag_agent.news import google_news_rss
from srag_agent.report.models import NewsReference
from tests.conftest import FIXTURES_DIR
from tests.drafts import good_draft
from tests.synthetic import REFERENCE_DATE, build_synthetic_database

RSS_FIXTURE = (FIXTURES_DIR / "google_news_srag.xml").read_bytes()


@pytest.fixture
def synthetic_settings(settings: Settings) -> Settings:
    build_synthetic_database(settings.data_dir)
    return settings


def _run(settings: Settings, responses: list[AIMessage], **kwargs: object) -> RunResult:
    model = build_chat_model(settings, fake_responses=responses)
    return run_report(settings, model=model, **kwargs)  # type: ignore[arg-type]


def _events(result: RunResult) -> list[dict]:
    return [json.loads(line) for line in result.audit_path.read_text(encoding="utf-8").splitlines()]


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
    assert "2 chamada(s) de ferramenta pedida(s) pelo modelo" in text
    assert "**Notícias:** google_news_rss;" in text
    for chart in result.chart_paths:
        assert chart.exists()

    events = _events(result)
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
    events = _events(result)
    assert events[-1]["payload"]["status"] == "unverified"
    assert any(e["name"] == "max_write_attempts" for e in events)
    assert any(e["type"] == "error" and e["name"] == "write_report" for e in events)


def test_invented_number_triggers_regeneration_then_passes(synthetic_settings: Settings) -> None:
    invented = good_draft().model_copy(
        update={"deep_dive": "Na UF SP a mortalidade chegou a 13,9% com 1234 casos."}
    )
    responses = [
        AIMessage(content="Sem aprofundamento."),
        AIMessage(content=invented.model_dump_json()),
        AIMessage(content=good_draft().model_dump_json()),
    ]
    result = _run(synthetic_settings, responses, include_news=False)

    assert result.validation is not None and result.validation.passed
    assert result.write_attempts == 2
    numeric = [e for e in _events(result) if e["name"] == "numeric_consistency"]
    assert [e["payload"]["passed"] for e in numeric] == [False, True]
    assert numeric[0]["payload"]["unverified"] == ["13,9%", "1234"]
    assert "⚠️" not in result.report_path.read_text(encoding="utf-8")


def test_persistent_invented_number_is_marked_unverified(synthetic_settings: Settings) -> None:
    invented = good_draft().model_copy(update={"deep_dive": "Foram 9999 casos (99,9%)."})
    responses = [AIMessage(content="ok")] + [AIMessage(content=invented.model_dump_json())] * 3
    result = _run(synthetic_settings, responses, include_news=False)

    assert result.validation is not None and not result.validation.passed
    assert result.write_attempts == 3
    text = result.report_path.read_text(encoding="utf-8")
    assert "não verificados" in text
    assert "Números sem origem nas ferramentas: 99,9%, 9999" in text


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
    events = _events(result)
    assert any(e["name"] == "tool_budget" and e["payload"]["passed"] is False for e in events)
    assert result.report_path.parent == tight.reports_dir / "x"


def test_analysis_decision_is_recorded_in_full(synthetic_settings: Settings) -> None:
    long_reasoning = "Decidi usar as notícias n1 e n2 porque " + "x" * 6000
    draft = AIMessage(content=good_draft().model_dump_json())
    result = _run(
        synthetic_settings, [AIMessage(content=long_reasoning), draft], include_news=False
    )
    decisions = [e for e in _events(result) if e["name"] == "analyze"]
    assert decisions[0]["payload"]["text"] == long_reasoning


def test_uf_scoped_run(synthetic_settings: Settings) -> None:
    responses = [AIMessage(content="ok"), AIMessage(content=good_draft().model_dump_json())]
    result = _run(synthetic_settings, responses, uf="sp", include_news=False)
    assert result.bundle.uf == "SP"
    assert result.report_path.name.endswith("-SP.md")
