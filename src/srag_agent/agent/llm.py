"""Chat model factory: real Anthropic model when a key exists, fake model otherwise."""

from __future__ import annotations

from collections.abc import Iterable

from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from srag_agent.config import Settings

FAKE_MODEL_NAME = "fake-chat-model"


def build_chat_model(
    settings: Settings,
    fake_responses: Iterable[AIMessage | str] | None = None,
) -> BaseChatModel:
    """Return the chat model used by the orchestrator.

    With `ANTHROPIC_API_KEY` set, returns `ChatAnthropic` configured only with model,
    output budget, timeout and retries: current Claude models reject sampling parameters
    such as `temperature`, `top_p` and `top_k`, so none are passed.
    Without a key (tests, CI), returns a fake model that replays `fake_responses`.
    """
    if settings.has_anthropic_key and fake_responses is None:
        from langchain_anthropic import ChatAnthropic

        assert settings.anthropic_api_key is not None
        return ChatAnthropic(
            model=settings.anthropic_model,
            api_key=settings.anthropic_api_key,
            max_tokens=settings.max_output_tokens,
            timeout=settings.llm_timeout_seconds,
            max_retries=3,
        )
    return GenericFakeChatModel(messages=iter(list(fake_responses or ["ok"])))


def model_label(settings: Settings, model: BaseChatModel) -> str:
    """Human-readable model name for audit logs and the report provenance section."""
    if isinstance(model, GenericFakeChatModel):
        return FAKE_MODEL_NAME
    return settings.anthropic_model
