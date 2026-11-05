"""Real API smoke test. Deselected by default (`-m 'not live'` in pyproject); run it with
`uv run pytest -m live`. Skipped when no key is configured."""

from __future__ import annotations

import pytest

from srag_agent.agent.llm import build_chat_model
from srag_agent.config import Settings


def _has_key() -> bool:
    return Settings().has_anthropic_key


@pytest.mark.live
@pytest.mark.skipif(not _has_key(), reason="ANTHROPIC_API_KEY not configured")
def test_anthropic_model_answers() -> None:
    reply = build_chat_model(Settings()).invoke("Responda só: ok")
    assert "ok" in str(reply.content).lower()
