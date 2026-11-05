"""Command-line entry point (`srag-agent`)."""

from __future__ import annotations

import typer

from srag_agent import __version__
from srag_agent.config import get_settings

app = typer.Typer(
    help="Agente GenAI para relatórios de SRAG (Open DATASUS + notícias).",
    no_args_is_help=True,
)


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
