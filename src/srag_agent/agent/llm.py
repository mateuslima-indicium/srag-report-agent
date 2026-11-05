"""Chat model factory and the two ways the graph talks to it (tools, structured output)."""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from pydantic import BaseModel

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
    if fake_responses is None:
        return GenericFakeChatModel(messages=itertools.cycle(["ok"]))
    return GenericFakeChatModel(messages=iter(list(fake_responses)))


def is_fake(model: BaseChatModel) -> bool:
    return isinstance(model, GenericFakeChatModel)


def model_label(settings: Settings, model: BaseChatModel) -> str:
    """Human-readable model name for audit logs and the report provenance section."""
    return FAKE_MODEL_NAME if is_fake(model) else settings.anthropic_model


def with_tools(model: BaseChatModel, tools: Sequence[BaseTool]) -> Runnable:
    """Bind tools when the model supports it; the fake model replays scripted tool calls."""
    if is_fake(model) or not tools:
        return model
    return model.bind_tools(list(tools))


def invoke_structured[SchemaT: BaseModel](
    model: BaseChatModel, messages: Sequence[BaseMessage], schema: type[SchemaT]
) -> SchemaT:
    """Structured output via Claude's native JSON-schema mode; JSON parsing for the fake model.

    `method="json_schema"` is required: Sonnet 5.5 / Opus 5.5 / Fable 5.1 no longer support
    forced tool calling, which is what the default `function_calling` method relies on.
    """
    if is_fake(model):
        reply = model.invoke(list(messages))
        return schema.model_validate_json(str(reply.content))
    structured = model.with_structured_output(schema, method="json_schema")
    result = structured.invoke(list(messages))
    if isinstance(result, schema):
        return result
    return schema.model_validate(result)
