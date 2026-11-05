"""LangGraph state shared by every node."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TypedDict

from langchain_core.messages import BaseMessage

from srag_agent.guardrails.output_validation import ValidationResult
from srag_agent.metrics.models import MetricsBundle
from srag_agent.news.models import NewsBatch
from srag_agent.report.models import ReportContent


class AgentState(TypedDict, total=False):
    """`total=False`: nodes return partial updates; LangGraph merges them."""

    # inputs
    reference_date: date | None
    uf: str | None
    include_news: bool
    output_dir: Path

    # deterministic layer
    bundle: MetricsBundle
    news: NewsBatch

    # analysis loop (LLM + tools)
    messages: list[BaseMessage]
    tool_calls_used: int
    analysis_notes: str

    # writing and validation
    draft: ReportContent | None
    validation: ValidationResult | None
    write_attempts: int
    validation_feedback: str

    # outputs
    report_path: Path | None
    chart_paths: list[Path]
