"""Tests for settings and the chat model factory."""

from __future__ import annotations

from pydantic import SecretStr

from srag_agent.agent.llm import FAKE_MODEL_NAME, build_chat_model, model_label
from srag_agent.config import Settings


def test_settings_without_key_reports_no_key(settings: Settings) -> None:
    assert not settings.has_anthropic_key
    assert not settings.has_tavily_key
    assert settings.parquet_path.name == "srag.parquet"


def test_blank_key_is_treated_as_missing(settings: Settings) -> None:
    blank = settings.model_copy(update={"anthropic_api_key": SecretStr("   ")})
    assert not blank.has_anthropic_key


def test_secret_is_not_exposed_in_repr(settings: Settings) -> None:
    secret = settings.model_copy(update={"anthropic_api_key": SecretStr("sk-test-123")})
    assert "sk-test-123" not in repr(secret)
    assert "sk-test-123" not in secret.model_dump_json()


def test_factory_returns_fake_model_without_key(settings: Settings) -> None:
    model = build_chat_model(settings, fake_responses=["olá"])
    assert model.invoke("qualquer coisa").content == "olá"
    assert model_label(settings, model) == FAKE_MODEL_NAME


def test_factory_builds_anthropic_model_with_key(settings: Settings) -> None:
    from langchain_anthropic import ChatAnthropic

    keyed = settings.model_copy(update={"anthropic_api_key": SecretStr("sk-test-123")})
    model = build_chat_model(keyed)
    assert isinstance(model, ChatAnthropic)
    assert model.model == keyed.anthropic_model
    assert model.temperature is None
    assert model.top_p is None
    assert model.top_k is None
    assert model_label(keyed, model) == keyed.anthropic_model
