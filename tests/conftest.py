"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from srag_agent.config import Settings

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings isolated from `.env` and from the real data directory."""
    return Settings(
        _env_file=None,
        anthropic_api_key=None,
        tavily_api_key=None,
        data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        audit_dir=tmp_path / "audit",
    )
