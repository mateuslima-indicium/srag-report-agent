"""Application settings loaded from environment variables and `.env`."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def project_relative(path: Path) -> str:
    """Path as written in reports and audit trails: relative to the repository, never to the
    user's home or current directory, so that versioned artifacts carry no local details."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.name


class Settings(BaseSettings):
    """Runtime configuration. Secrets are never logged or rendered."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    tavily_api_key: SecretStr | None = None

    data_dir: Path = PROJECT_ROOT / "data"
    reports_dir: Path = PROJECT_ROOT / "reports"
    audit_dir: Path = PROJECT_ROOT / "audit"

    reference_date: date | None = None
    max_tool_calls: int = Field(default=8, ge=0)
    max_news_items: int = Field(default=8, ge=0, le=30)
    sql_row_limit: int = Field(default=200, ge=1, le=1000)
    max_output_tokens: int = Field(default=8000, ge=256)
    llm_timeout_seconds: float = Field(default=120.0, gt=0)
    max_write_attempts: int = Field(default=3, ge=1)
    max_total_tokens: int = Field(default=200_000, ge=10_000)

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def parquet_path(self) -> Path:
        return self.data_dir / "processed" / "srag.parquet"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "srag.duckdb"

    @property
    def has_anthropic_key(self) -> bool:
        return bool(self.anthropic_api_key and self.anthropic_api_key.get_secret_value().strip())

    @property
    def has_tavily_key(self) -> bool:
        return bool(self.tavily_api_key and self.tavily_api_key.get_secret_value().strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
