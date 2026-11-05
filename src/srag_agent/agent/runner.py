"""Entry point that wires settings, database, audit, model, tools and the graph together."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from langchain_core.language_models import BaseChatModel

from srag_agent import __version__
from srag_agent.agent.callbacks import AuditCallbackHandler
from srag_agent.agent.graph import GraphContext, build_graph
from srag_agent.agent.llm import build_chat_model, model_label
from srag_agent.audit import AuditLogger
from srag_agent.config import Settings
from srag_agent.data.db import ensure_database, file_sha256, open_readonly
from srag_agent.guardrails.output_validation import ValidationResult
from srag_agent.metrics.models import MetricsBundle
from srag_agent.report.models import ReportContent
from srag_agent.tools import build_tools

RECURSION_LIMIT = 60


@dataclass
class RunResult:
    run_id: str
    report_path: Path
    chart_paths: list[Path]
    audit_path: Path
    bundle: MetricsBundle
    draft: ReportContent | None
    validation: ValidationResult | None
    tool_calls_used: int
    write_attempts: int
    model: str


def run_report(
    settings: Settings,
    reference_date: date | None = None,
    uf: str | None = None,
    include_news: bool = True,
    output_dir: Path | None = None,
    model: BaseChatModel | None = None,
) -> RunResult:
    """Run the whole graph once and return where the report landed."""
    database = ensure_database(settings.parquet_path, settings.db_path)
    audit = AuditLogger(settings.audit_dir)
    chat_model = model or build_chat_model(settings)
    name = model_label(settings, chat_model)
    audit.log(
        "run_start",
        "srag-report-agent",
        version=__version__,
        python=platform.python_version(),
        model=name,
        reference_date=reference_date.isoformat() if reference_date else None,
        uf=uf,
        include_news=include_news,
        parquet_sha256=file_sha256(settings.parquet_path),
        limits={
            "max_tool_calls": settings.max_tool_calls,
            "max_news_items": settings.max_news_items,
            "sql_row_limit": settings.sql_row_limit,
            "max_write_attempts": settings.max_write_attempts,
        },
    )
    handler = AuditCallbackHandler(audit, name)
    with open_readonly(database) as con:
        ctx = GraphContext(
            settings=settings, con=con, audit=audit, model=chat_model, tools=[], model_name=name
        )
        ctx.tools = build_tools(con, audit, lambda: ctx.news, settings.sql_row_limit)
        graph = build_graph(ctx)
        try:
            final = graph.invoke(
                {
                    "reference_date": reference_date,
                    "uf": uf,
                    "include_news": include_news,
                    "output_dir": output_dir or settings.reports_dir,
                },
                config={"callbacks": [handler], "recursion_limit": RECURSION_LIMIT},
            )
        except Exception as error:
            audit.log(
                "run_end",
                "srag-report-agent",
                status="error",
                error=f"{type(error).__name__}: {error}",
            )
            raise
    validation = final.get("validation")
    audit.log(
        "run_end",
        "srag-report-agent",
        status="ok" if validation is not None and validation.passed else "unverified",
        report=str(final["report_path"]),
        llm_calls=handler.calls,
        input_tokens=handler.total_input_tokens,
        output_tokens=handler.total_output_tokens,
        tool_calls_used=final.get("tool_calls_used", 0),
        write_attempts=final.get("write_attempts", 0),
    )
    return RunResult(
        run_id=audit.run_id,
        report_path=final["report_path"],
        chart_paths=final["chart_paths"],
        audit_path=audit.path,
        bundle=final["bundle"],
        draft=final.get("draft"),
        validation=validation,
        tool_calls_used=final.get("tool_calls_used", 0),
        write_attempts=final.get("write_attempts", 0),
        model=name,
    )
