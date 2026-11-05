"""Output guardrails: numeric consistency, PII, clinical advice, caveats, structure."""

from __future__ import annotations

import json

import pytest

from srag_agent.audit import AuditLogger
from srag_agent.data.db import open_readonly
from srag_agent.guardrails.numeric_consistency import check_numbers, extract_numbers
from srag_agent.guardrails.output_validation import (
    check_caveats,
    check_clinical_advice,
    check_pii,
    check_structure,
    validate_report,
)
from srag_agent.guardrails.pii import find_pii
from srag_agent.metrics import collect_metrics
from srag_agent.news.models import NewsBatch, NewsItem
from srag_agent.report.models import MetricCommentary
from tests.drafts import good_draft
from tests.synthetic import build_synthetic_database


@pytest.fixture(scope="module")
def bundle(tmp_path_factory: pytest.TempPathFactory):
    database = build_synthetic_database(tmp_path_factory.mktemp("guardrails"))
    with open_readonly(database) as con:
        return collect_metrics(con)


def test_extract_numbers_ignores_dates_ids_and_small_counts() -> None:
    text = (
        "Em 01/11/2026 (SE 44, [n2]) houve 10.788 casos, +61,7% em 30 dias, 11,8% de "
        "mortalidade, faixa 70-79 e 80+, 2026-10-03, 5 UFs, -3,2%."
    )
    percents, integers = extract_numbers(text)
    assert percents == [61.7, 11.8, -3.2]
    assert integers == [10788, 30]


def test_window_sizes_are_allowed(bundle) -> None:
    draft = good_draft().model_copy(
        update={"deep_dive": "Janelas de 7 e 30 dias; os últimos 14 dias são preliminares."}
    )
    assert check_numbers(draft, bundle, NewsBatch(), []).passed


def test_numbers_from_metrics_are_accepted(bundle) -> None:
    check = check_numbers(good_draft(), bundle, NewsBatch(), [])
    assert check.passed, check.unverified


def test_invented_numbers_are_flagged(bundle) -> None:
    draft = good_draft().model_copy(
        update={"deep_dive": "Em SP houve 1234 casos e a mortalidade foi de 13,9%."}
    )
    check = check_numbers(draft, bundle, NewsBatch(), [])
    assert not check.passed
    assert check.unverified == ["13,9%", "1234"]
    assert "Números sem origem" in check.issue


def test_numbers_from_tool_outputs_and_news_are_accepted(bundle) -> None:
    sql_output = json.dumps({"columns": ["uf", "n"], "rows": [["SP", 1234]]})
    growth_output = json.dumps({"name": "case_growth_30d", "value": 0.0996, "numerator": 287})
    news = NewsBatch(
        items=[
            NewsItem(
                id="n1",
                title="Cidade chega a 20 mortes por SRAG e soma 694 hospitalizações",
                source="X",
                url="https://x/1",
                provider="t",
            )
        ]
    )
    draft = good_draft(["n1"]).model_copy(
        update={
            "deep_dive": "SP teve 1234 casos; Sergipe subiu +10,0% (287 casos).",
            "news_context": "[n1] fala em 20 mortes e 694 hospitalizações.",
        }
    )
    assert check_numbers(draft, bundle, news, [sql_output, growth_output]).passed


def test_percent_sign_is_not_required(bundle) -> None:
    """The growth metric is +61,7%; "crescimento de 61,7%" and "-61,7%" are the same number."""
    draft = good_draft().model_copy(
        update={"deep_dive": "Crescimento de 61,7% em 30 dias, contra uma queda de 3,2% antes."}
    )
    check = check_numbers(draft, bundle, NewsBatch(), [])
    assert check.unverified == ["3,2%"]


def test_tool_window_sizes_are_allowed(bundle) -> None:
    draft = good_draft().model_copy(
        update={"deep_dive": "Na janela de 90 dias e na de 60 dias a leitura é parecida."}
    )
    assert check_numbers(draft, bundle, NewsBatch(), []).passed


def test_rounding_tolerance(bundle) -> None:
    draft = good_draft().model_copy(update={"deep_dive": "Mortalidade de 11,7% (84 casos)."})
    assert check_numbers(draft, bundle, NewsBatch(), []).passed  # 11.8 - 0.1, 85 - 1
    worse = good_draft().model_copy(update={"deep_dive": "Mortalidade de 11,5% (83 casos)."})
    assert check_numbers(worse, bundle, NewsBatch(), []).unverified == ["11,5%", "83"]


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("paciente CPF 123.456.789-09", "cpf"),
        ("contato maria.silva@example.com", "email"),
        ("telefone (11) 98765-4321", "phone"),
        ("cartão 898001234567890", "cns"),
        ("notificação 31776951387507", "notification_number"),
    ],
)
def test_pii_patterns(text: str, label: str) -> None:
    assert label in find_pii(text)


def test_ordinary_report_text_has_no_pii() -> None:
    text = "Em 03/10/2026 houve 10.788 casos e 191 óbitos (4,1%), janela 2026-10-03 a 2026-11-01."
    assert find_pii(text) == []
    assert check_pii(good_draft()).passed


@pytest.mark.parametrize(
    "sentence",
    [
        "Recomendamos que você tome oseltamivir nas primeiras 48 horas.",
        "Se você sentir falta de ar, procure um médico imediatamente.",
        "O paciente deve iniciar antibiótico.",
    ],
)
def test_clinical_advice_is_blocked(sentence: str) -> None:
    draft = good_draft().model_copy(update={"deep_dive": sentence})
    assert not check_clinical_advice(draft).passed


def test_population_level_language_is_allowed() -> None:
    draft = good_draft().model_copy(
        update={"deep_dive": "A vacinação contra gripe segue recomendada pelo PNI para idosos."}
    )
    assert check_clinical_advice(draft).passed


def test_language_is_checked_per_field(bundle) -> None:
    english = good_draft().model_copy(
        update={
            "executive_summary": (
                "The mortality rate among cases with a known outcome is 11.8% and cases "
                "increased with the reporting delay; however, vaccination remains low."
            )
        }
    )
    result = check_structure(english, bundle, NewsBatch())
    assert result.checks["language_pt_br"] is False
    assert "executive_summary" in result.issues[0]
    assert check_structure(good_draft(), bundle, NewsBatch()).checks["language_pt_br"] is True


def test_caveats_must_be_mentioned() -> None:
    draft = good_draft()
    draft.metric_sections[2] = MetricCommentary(
        metric_name="mortality_rate", headline="4,1%", interpretation="Taxa baixa."
    )
    result = check_caveats(draft)
    assert not result.passed
    assert "mortality_rate" in result.issues[0]


def test_validate_report_audits_every_check(bundle, tmp_path) -> None:
    audit = AuditLogger(tmp_path, run_id="g")
    result = validate_report(good_draft(), bundle, NewsBatch(), audit, [])
    assert result.passed
    assert set(result.checks) >= {
        "all_metrics_commented",
        "caveats_present",
        "no_clinical_advice",
        "no_pii",
        "numeric_consistency",
    }
    assert {e.name for e in audit.of_type("guardrail")} == {
        "report_structure",
        "metric_caveats",
        "clinical_advice",
        "pii",
        "numeric_consistency",
    }
