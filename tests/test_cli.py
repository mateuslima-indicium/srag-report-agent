"""CLI commands through typer's runner, on the synthetic database."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from srag_agent import cli
from srag_agent.config import Settings
from tests.synthetic import build_synthetic_database

runner = CliRunner()


@pytest.fixture
def cli_settings(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    build_synthetic_database(settings.data_dir)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    return settings


def test_version_command(cli_settings: Settings) -> None:
    result = runner.invoke(cli.app, ["version"])
    assert result.exit_code == 0
    assert "chave Anthropic configurada: não" in result.stdout


def test_metrics_command_prints_table(cli_settings: Settings) -> None:
    result = runner.invoke(cli.app, ["metrics", "--reference-date", "2026-10-31"])
    assert result.exit_code == 0
    assert "Taxa de mortalidade" in result.stdout
    assert "11,8%" in result.stdout


def test_metrics_command_rejects_bad_uf(cli_settings: Settings) -> None:
    result = runner.invoke(cli.app, ["metrics", "--uf", "XX"])
    assert result.exit_code == 1
    assert "UF desconhecida" in result.output


@pytest.mark.parametrize("command", ["metrics", "charts", "report"])
def test_malformed_reference_date_fails_cleanly(cli_settings: Settings, command: str) -> None:
    result = runner.invoke(cli.app, [command, "--reference-date", "abc"])
    assert result.exit_code == 1
    assert "--reference-date inválida" in result.output
    assert "Traceback" not in result.output
    assert not cli_settings.audit_dir.exists()


def test_report_rejects_bad_uf_before_running(cli_settings: Settings) -> None:
    result = runner.invoke(cli.app, ["report", "--uf", "XX", "--no-news"])
    assert result.exit_code == 1
    assert "UF desconhecida" in result.output
    assert not cli_settings.audit_dir.exists()


def test_charts_command_writes_png(cli_settings: Settings, tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["charts", "--output", str(tmp_path / "c")])
    assert result.exit_code == 0
    assert (tmp_path / "c" / "casos-diarios.png").exists()


def test_report_command_without_key_uses_fake_model(cli_settings: Settings, tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["report", "--no-news", "--output", str(tmp_path / "r")])
    assert result.exit_code == 0, result.output
    assert "modelo fake" in result.output
    assert "fake-chat-model" in result.stdout
    assert list((tmp_path / "r").glob("relatorio-srag-*.md"))


def test_api_authentication_error_is_a_clear_message(
    cli_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import anthropic
    import httpx

    from srag_agent.agent import runner as agent_runner

    def failing_run(*args: object, **kwargs: object) -> None:
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(401, request=request)
        raise anthropic.AuthenticationError("Invalid bearer token", response=response, body=None)

    monkeypatch.setattr(agent_runner, "run_report", failing_run)
    result = runner.invoke(cli.app, ["report", "--no-news"])
    assert result.exit_code == 1
    assert "ANTHROPIC_API_KEY está inválida" in result.output
    assert "Traceback" not in result.output
