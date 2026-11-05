"""Output guardrail: structural and language checks on the LLM-written report content."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from srag_agent.audit import AuditLogger
from srag_agent.metrics.models import MetricsBundle
from srag_agent.news.models import NewsBatch
from srag_agent.report.models import ReportContent

MIN_SUMMARY_CHARS = 80
_ENGLISH_MARKERS = re.compile(
    r"\b(the|and|with|cases|increase|decrease|mortality|vaccination|however|therefore)\b",
    re.IGNORECASE,
)
_PORTUGUESE_MARKERS = re.compile(
    r"\b(de|da|do|que|com|casos|não|para|uma|entre|óbitos|mortalidade|vacinação)\b",
    re.IGNORECASE,
)


class ValidationResult(BaseModel):
    passed: bool
    issues: list[str] = Field(default_factory=list)
    checks: dict[str, bool] = Field(default_factory=dict)

    def add(self, check: str, ok: bool, issue: str | None = None) -> None:
        self.checks[check] = ok
        if not ok:
            self.passed = False
            self.issues.append(issue or check)


def _looks_portuguese(text: str) -> bool:
    english = len(_ENGLISH_MARKERS.findall(text))
    portuguese = len(_PORTUGUESE_MARKERS.findall(text))
    return portuguese >= english


def check_structure(
    draft: ReportContent, bundle: MetricsBundle, news: NewsBatch
) -> ValidationResult:
    """Every metric commented once, citations valid, language pt-BR, summary not empty."""
    result = ValidationResult(passed=True)
    expected = [metric.name for metric in bundle.metrics]
    commented = [section.metric_name for section in draft.metric_sections]
    missing = [name for name in expected if name not in commented]
    unknown = [name for name in commented if name not in expected]
    result.add(
        "all_metrics_commented",
        not missing and not unknown,
        f"Métricas sem seção: {missing}; nomes desconhecidos: {unknown}",
    )
    result.add(
        "summary_length",
        len(draft.executive_summary.strip()) >= MIN_SUMMARY_CHARS,
        "Resumo executivo curto demais",
    )
    valid_ids = {item.id for item in news.items}
    bad_refs = sorted(draft.cited_ids - valid_ids)
    inline_ids = set(re.findall(r"\[(n\d+)\]", draft.news_context))
    bad_inline = sorted(inline_ids - valid_ids)
    result.add(
        "news_citations_valid",
        not bad_refs and not bad_inline,
        f"Citações de notícias inexistentes: {bad_refs + bad_inline}",
    )
    full_text = " ".join(
        [
            draft.executive_summary,
            draft.news_context,
            draft.deep_dive,
            *(s.interpretation for s in draft.metric_sections),
            *draft.limitations,
        ]
    )
    result.add(
        "language_pt_br", _looks_portuguese(full_text), "Texto não parece estar em português"
    )
    result.add("limitations_present", bool(draft.limitations), "Seção de limitações vazia")
    return result


def validate_report(
    draft: ReportContent, bundle: MetricsBundle, news: NewsBatch, audit: AuditLogger
) -> ValidationResult:
    """Run every output guardrail and merge the results (each one is also audited)."""
    result = check_structure(draft, bundle, news)
    audit.log("guardrail", "report_structure", passed=result.passed, issues=result.issues)
    return result
