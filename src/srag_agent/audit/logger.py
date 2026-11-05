"""Append-only JSONL audit logger, one file per run."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from srag_agent.audit.events import AuditEvent, EventType


def new_run_id() -> str:
    return secrets.token_hex(4)


class AuditLogger:
    """Writes `AuditEvent`s to `audit/run-<timestamp>-<id>.jsonl` and keeps them in memory."""

    def __init__(self, audit_dir: Path, run_id: str | None = None) -> None:
        self.run_id = run_id or new_run_id()
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        audit_dir.mkdir(parents=True, exist_ok=True)
        self.path = audit_dir / f"run-{stamp}-{self.run_id}.jsonl"
        self.events: list[AuditEvent] = []

    def log(self, type: EventType, name: str, **payload: Any) -> AuditEvent:
        event = AuditEvent(
            run_id=self.run_id, seq=len(self.events), type=type, name=name, payload=payload
        )
        self.events.append(event)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")
        return event

    def count(self, type: EventType, name: str | None = None) -> int:
        return sum(1 for e in self.events if e.type == type and (name is None or e.name == name))

    def of_type(self, type: EventType) -> list[AuditEvent]:
        return [e for e in self.events if e.type == type]
