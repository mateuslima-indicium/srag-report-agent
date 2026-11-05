"""Output guardrails on the LLM-written report content.

Checks: structure (every metric commented, valid citations, pt-BR, limitations), mandatory
caveats per metric, no individual clinical advice, no PII, and numeric consistency against
the tool results of the run. Each check is audited; failures feed the writer's retry.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from srag_agent.audit import AuditLogger
from srag_agent.guardrails.numeric_consistency import check_numbers, draft_text
from srag_agent.guardrails.pii import find_pii
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

REQUIRED_CAVEAT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "case_growth_7d": ("prelimin", "atraso"),
    "case_growth_30d": ("prelimin", "atraso"),
    "mortality_rate": ("desfecho",),
    "icu_rate": ("leito", "ocupação", "proporção"),
    "vaccination_covid": ("população", "cobertura", "proxy"),
    "vaccination_flu": ("população", "cobertura", "proxy"),
}
"""Each metric's interpretation must mention at least one of these words."""

CLINICAL_ADVICE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(tome|tomar|ingira|ingerir|use|utilize|administre)\b.{0,40}"
        r"\b(oseltamivir|tamiflu|antibi[oó]tico|antiviral|cortic[oó]ide|ibuprofeno|paracetamol|"
        r"dipirona|medicamento|rem[eé]dio|dose)\b",
        r"\brecomend\w*\s+(que\s+)?(voc[eê]|o\s+paciente|a\s+paciente)\b",
        r"\b(voc[eê]|o\s+paciente|a\s+paciente)\s+(deve|precisa|dever[aá])\b",
        r"\bprocure\s+(um|o|uma)\s+(m[eé]dico|pronto[- ]socorro|hospital|UPA)\b",
        r"\bse\s+voc[eê]\s+(sentir|tiver|apresentar)\b",
        r"\bautomedica",
    )
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
    result.add(
        "language_pt_br",
        _looks_portuguese(draft_text(draft)),
        "Texto não parece estar em português",
    )
    result.add("limitations_present", bool(draft.limitations), "Seção de limitações vazia")
    return result


def check_caveats(draft: ReportContent) -> ValidationResult:
    """The interpretation of each metric must carry its mandatory caveat."""
    result = ValidationResult(passed=True)
    missing: list[str] = []
    for section in draft.metric_sections:
        keywords = REQUIRED_CAVEAT_KEYWORDS.get(section.metric_name, ())
        text = f"{section.headline} {section.interpretation}".casefold()
        if keywords and not any(keyword in text for keyword in keywords):
            missing.append(f"{section.metric_name} (mencione: {' ou '.join(keywords)})")
    result.add(
        "caveats_present",
        not missing,
        f"Seções sem a ressalva obrigatória da métrica: {missing}",
    )
    return result


def check_clinical_advice(draft: ReportContent) -> ValidationResult:
    result = ValidationResult(passed=True)
    text = draft_text(draft)
    hits = [pattern.pattern[:40] for pattern in CLINICAL_ADVICE_PATTERNS if pattern.search(text)]
    result.add(
        "no_clinical_advice",
        not hits,
        "Texto contém recomendação clínica individual; descreva apenas tendências populacionais",
    )
    return result


def check_pii(draft: ReportContent) -> ValidationResult:
    result = ValidationResult(passed=True)
    labels = find_pii(draft_text(draft))
    result.add("no_pii", not labels, f"Texto contém dados pessoais ({', '.join(labels)})")
    return result


def merge(*results: ValidationResult) -> ValidationResult:
    merged = ValidationResult(passed=True)
    for result in results:
        merged.checks.update(result.checks)
        merged.issues.extend(result.issues)
        merged.passed = merged.passed and result.passed
    return merged


def validate_report(
    draft: ReportContent,
    bundle: MetricsBundle,
    news: NewsBatch,
    audit: AuditLogger,
    tool_outputs: list[str] | None = None,
) -> ValidationResult:
    """Run every output guardrail; each one is audited individually, then merged."""
    structure = check_structure(draft, bundle, news)
    audit.log("guardrail", "report_structure", passed=structure.passed, issues=structure.issues)
    caveats = check_caveats(draft)
    audit.log("guardrail", "metric_caveats", passed=caveats.passed, issues=caveats.issues)
    clinical = check_clinical_advice(draft)
    audit.log("guardrail", "clinical_advice", passed=clinical.passed, issues=clinical.issues)
    pii = check_pii(draft)
    audit.log("guardrail", "pii", passed=pii.passed, issues=pii.issues)
    numbers = check_numbers(draft, bundle, news, tool_outputs or [])
    numeric = ValidationResult(passed=True)
    numeric.add("numeric_consistency", numbers.passed, numbers.issue)
    audit.log(
        "guardrail",
        "numeric_consistency",
        passed=numbers.passed,
        checked=numbers.checked,
        unverified=numbers.unverified,
    )
    return merge(structure, caveats, clinical, pii, numeric)
