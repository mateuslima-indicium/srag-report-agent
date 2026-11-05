"""Markdown report renderer with the "Como este relatório foi produzido" provenance section."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from srag_agent import __version__
from srag_agent.data.db import file_sha256
from srag_agent.guardrails.output_validation import ValidationResult
from srag_agent.metrics.models import MetricsBundle
from srag_agent.news.models import NewsBatch
from srag_agent.report.charts import plot_daily_cases, plot_monthly_cases
from srag_agent.report.models import ReportContent

if TYPE_CHECKING:
    from srag_agent.agent.graph import GraphContext
    from srag_agent.agent.state import AgentState

UNVERIFIED_BANNER = (
    "> ⚠️ **Atenção:** os guardrails de saída encontraram problemas que o modelo não corrigiu "
    "após as tentativas permitidas. Os trechos redigidos pelo modelo devem ser lidos como "
    "**não verificados**; os números da tabela e dos gráficos são determinísticos e permanecem "
    "válidos."
)


class Provenance(BaseModel):
    run_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    model: str
    parquet_sha256: str
    parquet_path: str
    latest_case_date: str
    news_queries: list[str]
    llm_calls: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    guardrails: list[dict[str, object]]
    audit_path: str
    app_version: str = __version__


def thousands(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _metrics_table(bundle: MetricsBundle) -> list[str]:
    lines = [
        "| Métrica | Valor | Numerador / denominador | Janela |",
        "|---|---:|---:|---|",
    ]
    for metric in bundle.metrics:
        lines.append(
            f"| {metric.label} | **{metric.formatted}** | "
            f"{thousands(metric.numerator)} / {thousands(metric.denominator)} | "
            f"{metric.window_start:%d/%m/%Y} a {metric.window_end:%d/%m/%Y} |"
        )
    return lines


def _metric_sections(draft: ReportContent | None, bundle: MetricsBundle) -> list[str]:
    lines: list[str] = []
    commentary = {s.metric_name: s for s in (draft.metric_sections if draft else [])}
    for metric in bundle.metrics:
        lines += [f"### {metric.label}", ""]
        section = commentary.get(metric.name)
        if section:
            lines += [f"**{section.headline}**", "", section.interpretation, ""]
        lines += [f"*Definição:* {metric.definition}", ""]
        lines += ["*Ressalvas:*", *(f"- {c}" for c in metric.caveats), ""]
    return lines


def _news_section(draft: ReportContent | None, news: NewsBatch) -> list[str]:
    lines = ["## Contexto das notícias", ""]
    if draft and draft.news_context:
        lines += [draft.news_context, ""]
    if not news.items:
        reason = "; ".join(news.errors) or "nenhum item encontrado"
        lines += [f"Nenhuma notícia disponível nesta execução ({reason}).", ""]
        return lines
    cited = draft.cited_ids if draft else set()
    lines += ["| Id | Data | Fonte | Título | Citada |", "|---|---|---|---|:---:|"]
    for item in news.items:
        when = item.published_at.strftime("%d/%m/%Y") if item.published_at else "n/d"
        mark = "sim" if item.id in cited else ""
        lines.append(
            f"| {item.id} | {when} | {item.source} | [{item.title}]({item.url}) | {mark} |"
        )
    if news.discarded:
        lines += [
            "",
            f"{len(news.discarded)} item(ns) descartado(s) pelo filtro de injeção de prompt.",
        ]
    lines.append("")
    return lines


def _provenance_section(provenance: Provenance, validation: ValidationResult | None) -> list[str]:
    lines = [
        "## Como este relatório foi produzido",
        "",
        f"- **Execução:** `{provenance.run_id}`, gerada em "
        f"{provenance.generated_at:%d/%m/%Y %H:%M} UTC por "
        f"`srag-report-agent {provenance.app_version}`.",
        f"- **Dados:** `{provenance.parquet_path}` (SHA-256 `{provenance.parquet_sha256[:16]}…`), "
        f"Sivep-Gripe/Open DATASUS, último caso em {provenance.latest_case_date}. "
        "Dados de-identificados: sem nomes, documentos, datas de nascimento, município ou "
        "texto livre.",
        f"- **Modelo:** `{provenance.model}`, {provenance.llm_calls} chamada(s), "
        f"{thousands(provenance.input_tokens)} tokens de entrada e "
        f"{thousands(provenance.output_tokens)} de saída.",
        f"- **Ferramentas:** {provenance.tool_calls} chamada(s) de ferramenta registradas; "
        "todos os números vêm de SQL determinístico sobre DuckDB, nunca do modelo.",
        f"- **Notícias:** Google News RSS, consultas: "
        f"{', '.join(provenance.news_queries) or 'n/a'}.",
        f"- **Auditoria completa:** `{provenance.audit_path}` "
        "(JSONL com cada chamada, decisão e guardrail).",
        "- **Guardrails executados:**",
    ]
    for event in provenance.guardrails:
        status = "ok" if event.get("passed") else "FALHOU"
        lines.append(f"  - `{event.get('name')}`: {status}")
    if validation is not None:
        checks = ", ".join(f"{k}={'ok' if v else 'falhou'}" for k, v in validation.checks.items())
        verdict = "aprovada" if validation.passed else "reprovada"
        lines.append(f"- **Validação final da saída:** {verdict} ({checks}).")
    return lines


def render_markdown(
    draft: ReportContent | None,
    bundle: MetricsBundle,
    news: NewsBatch,
    validation: ValidationResult | None,
    provenance: Provenance,
    chart_files: tuple[str, str],
) -> str:
    scope = f"UF {bundle.uf}" if bundle.uf else "Brasil"
    verified = validation is not None and validation.passed
    lines = [
        f"# Relatório de SRAG: {scope}, referência {bundle.reference_date:%d/%m/%Y}",
        "",
        "Síndrome Respiratória Aguda Grave (Sivep-Gripe / Open DATASUS). "
        "Métricas calculadas por código; interpretação redigida por um modelo de linguagem "
        "a partir exclusivamente desses números e validada por guardrails.",
        "",
    ]
    if not verified:
        lines += [UNVERIFIED_BANNER, ""]
    lines += ["## Resumo executivo", "", draft.executive_summary if draft else "(sem resumo)", ""]
    lines += ["## Métricas", "", *_metrics_table(bundle), ""]
    daily, monthly = chart_files
    lines += [
        "## Gráficos",
        "",
        f"![Casos diários (30 dias)]({daily})",
        "",
        f"![Casos mensais (12 meses)]({monthly})",
        "",
    ]
    lines += ["## Interpretação por métrica", "", *_metric_sections(draft, bundle)]
    if draft and draft.deep_dive:
        lines += ["## Aprofundamento", "", draft.deep_dive, ""]
    lines += _news_section(draft, news)
    lines += ["## Limitações", ""]
    limitations = draft.limitations if draft else []
    lines += [f"- {item}" for item in limitations] or ["- (não redigidas)"]
    lines.append("")
    if validation is not None and not validation.passed:
        lines += [
            "### Problemas apontados pelos guardrails",
            "",
            *(f"- {issue}" for issue in validation.issues),
            "",
        ]
    lines += _provenance_section(provenance, validation)
    lines.append("")
    return "\n".join(lines)


def write_report_files(ctx: GraphContext, state: AgentState) -> tuple[Path, list[Path]]:
    """Render charts and Markdown into the output folder; returns (markdown, [charts])."""
    bundle = state["bundle"]
    folder = state.get("output_dir") or ctx.settings.reports_dir
    folder.mkdir(parents=True, exist_ok=True)
    suffix = f"-{bundle.uf}" if bundle.uf else ""
    stem = f"relatorio-srag-{bundle.reference_date.isoformat()}{suffix}"
    daily = plot_daily_cases(
        bundle.get_series("daily_cases_30d"), folder / f"{stem}-casos-diarios.png"
    )
    monthly = plot_monthly_cases(
        bundle.get_series("monthly_cases_12m"), folder / f"{stem}-casos-mensais.png"
    )
    llm_events = ctx.audit.of_type("llm_call")
    parquet = ctx.settings.parquet_path
    provenance = Provenance(
        run_id=ctx.audit.run_id,
        model=ctx.model_name,
        parquet_sha256=file_sha256(parquet) if parquet.exists() else "n/a",
        parquet_path=_relative(parquet),
        latest_case_date=bundle.latest_case_date.isoformat(),
        news_queries=state["news"].queries,
        llm_calls=len(llm_events),
        tool_calls=ctx.audit.count("tool_call"),
        input_tokens=sum(int(e.payload.get("input_tokens") or 0) for e in llm_events),
        output_tokens=sum(int(e.payload.get("output_tokens") or 0) for e in llm_events),
        guardrails=[
            {"name": e.name, "passed": e.payload.get("passed")}
            for e in ctx.audit.of_type("guardrail")
        ],
        audit_path=_relative(ctx.audit.path),
    )
    markdown = render_markdown(
        state.get("draft"),
        bundle,
        state["news"],
        state.get("validation"),
        provenance,
        (daily.name, monthly.name),
    )
    report_path = folder / f"{stem}.md"
    report_path.write_text(markdown, encoding="utf-8")
    return report_path, [daily, monthly]


def _relative(path: Path) -> str:
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()
