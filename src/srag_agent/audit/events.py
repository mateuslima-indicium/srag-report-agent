"""Audit event model written to the JSONL trail of every run."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "run_start",
    "llm_call",
    "tool_call",
    "guardrail",
    "decision",
    "news_fetch",
    "error",
    "run_end",
]


class AuditEvent(BaseModel):
    """One line of the audit log. `payload` never contains secrets or individual records."""

    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    run_id: str
    seq: int
    type: EventType
    name: str = Field(description="Node, tool, guardrail or model the event refers to")
    payload: dict[str, Any] = Field(default_factory=dict)
