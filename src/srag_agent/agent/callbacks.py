"""LangChain callback that records every LLM call in the audit trail."""

from __future__ import annotations

import hashlib
import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

from srag_agent.audit import AuditLogger


def _prompt_hash(messages: list[list[BaseMessage]]) -> str:
    text = "\n".join(str(m.content) for batch in messages for m in batch)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class AuditCallbackHandler(BaseCallbackHandler):
    """Logs model, prompt hash, token usage, latency and tool calls requested."""

    def __init__(self, audit: AuditLogger, model_name: str) -> None:
        super().__init__()
        self.audit = audit
        self.model_name = model_name
        self._started: dict[UUID, tuple[float, str, int]] = {}

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        count = sum(len(batch) for batch in messages)
        self._started[run_id] = (time.perf_counter(), _prompt_hash(messages), count)

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        started, prompt_hash, message_count = self._started.pop(
            run_id, (time.perf_counter(), "", 0)
        )
        generation = response.generations[0][0] if response.generations else None
        message = getattr(generation, "message", None)
        usage = getattr(message, "usage_metadata", None) or {}
        tool_calls = [call["name"] for call in getattr(message, "tool_calls", []) or []]
        self.audit.log(
            "llm_call",
            self.model_name,
            prompt_hash=prompt_hash,
            messages=message_count,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            latency_ms=round((time.perf_counter() - started) * 1000),
            tool_calls_requested=tool_calls,
            stop_reason=(getattr(message, "response_metadata", None) or {}).get("stop_reason"),
        )

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._started.pop(run_id, None)
        self.audit.log(
            "error", self.model_name, where="llm", error=f"{type(error).__name__}: {error}"
        )
