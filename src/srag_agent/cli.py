"""Command-line entry point (`srag-agent`)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from srag_agent import __version__
from srag_agent.config import Settings, get_settings
from srag_agent.data.db import ensure_database, open_readonly
from srag_agent.metrics import MetricsBundle, collect_metrics
from srag_agent.report.charts import plot_daily_cases, plot_monthly_cases

app = typer.Typer(
    help="Agente GenAI para relatórios de SRAG (Open DATASUS + notícias).",
    no_args_is_help=True,
)

ReferenceDateOption = Annotated[
    str | None,
    typer.Option("--reference-date", help="Data de referência (YYYY-MM-DD). Padrão: último caso."),
]
UfOption = Annotated[str | None, typer.Option("--uf", help="Sigla da UF, ex. SP. Padrão: Brasil.")]


@app.callback()
def main() -> None:
    """Agente GenAI para relatórios de SRAG (Open DATASUS + notícias)."""


@app.command()
def version() -> None:
    """Mostra a versão e a configuração não sensível."""
    settings = get_settings()
    typer.echo(f"srag-report-agent {__version__}")
    typer.echo(f"modelo: {settings.anthropic_model}")
    typer.echo(f"chave Anthropic configurada: {'sim' if settings.has_anthropic_key else 'não'}")
    typer.echo(f"banco: {settings.db_path}")


@app.command()
def metrics(reference_date: ReferenceDateOption = None, uf: UfOption = None) -> None:
    """Calcula as métricas determinísticas e imprime uma tabela."""
    bundle = _collect(get_settings(), reference_date, uf)
    typer.echo(f"Data de referência: {bundle.reference_date}  |  escopo: {bundle.uf or 'Brasil'}")
    typer.echo(f"{'métrica':<58} {'valor':>9} {'num':>8} {'den':>8}  janela")
    for metric in bundle.metrics:
        typer.echo(
            f"{metric.label[:58]:<58} {metric.formatted:>9} "
            f"{metric.numerator:>8} {metric.denominator:>8}"
            f"  {metric.window_start} a {metric.window_end}"
        )
    for series in bundle.series:
        typer.echo(f"{series.label}: {series.total} casos em {len(series.points)} períodos")


@app.command()
def charts(
    reference_date: ReferenceDateOption = None,
    uf: UfOption = None,
    output: Annotated[Path | None, typer.Option("--output", help="Pasta de saída.")] = None,
) -> None:
    """Gera os dois gráficos (PNG) do relatório."""
    settings = get_settings()
    bundle = _collect(settings, reference_date, uf)
    folder = output or settings.reports_dir
    daily = plot_daily_cases(bundle.get_series("daily_cases_30d"), folder / "casos-diarios.png")
    monthly = plot_monthly_cases(
        bundle.get_series("monthly_cases_12m"), folder / "casos-mensais.png"
    )
    typer.echo(f"{daily}\n{monthly}")


def _collect(settings: Settings, reference_date: str | None, uf: str | None) -> MetricsBundle:
    parsed = date.fromisoformat(reference_date) if reference_date else settings.reference_date
    try:
        database = ensure_database(settings.parquet_path, settings.db_path)
        with open_readonly(database) as con:
            return collect_metrics(con, parsed, uf)
    except (FileNotFoundError, ValueError) as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error


@app.command()
def report(
    reference_date: ReferenceDateOption = None,
    uf: UfOption = None,
    no_news: Annotated[bool, typer.Option("--no-news", help="Não consultar notícias.")] = False,
    output: Annotated[Path | None, typer.Option("--output", help="Pasta de saída.")] = None,
) -> None:
    """Executa o agente e gera o relatório (Markdown + 2 PNG + auditoria JSONL)."""
    from srag_agent.agent.runner import run_report

    settings = get_settings()
    parsed = date.fromisoformat(reference_date) if reference_date else settings.reference_date
    if not settings.has_anthropic_key:
        typer.secho(
            "ANTHROPIC_API_KEY ausente: o relatório será gerado com o modelo fake "
            "(sem texto real).",
            fg=typer.colors.YELLOW,
            err=True,
        )
    try:
        result = run_report(settings, parsed, uf, include_news=not no_news, output_dir=output)
    except (FileNotFoundError, ValueError) as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error
    status = "aprovado" if result.validation and result.validation.passed else "NÃO VERIFICADO"
    typer.echo(f"relatório: {result.report_path}")
    for chart in result.chart_paths:
        typer.echo(f"gráfico:   {chart}")
    typer.echo(f"auditoria: {result.audit_path}")
    typer.echo(
        f"execução {result.run_id}: modelo {result.model}, {result.tool_calls_used} tool call(s), "
        f"{result.write_attempts} tentativa(s) de redação, validação {status}"
    )
