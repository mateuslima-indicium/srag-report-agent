"""Report drafts shared by the graph and guardrail tests."""

from __future__ import annotations

from srag_agent.report.models import MetricCommentary, NewsReference, ReportContent

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
                "Os casos recentes de SRAG são preliminares por atraso de notificação; "
                "a mortalidade considera apenas casos com desfecho conhecido; a taxa de UTI é "
                "uma proporção de internados, não ocupação de leitos; a vacinação é um proxy "
                "entre pacientes, não cobertura populacional."
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
