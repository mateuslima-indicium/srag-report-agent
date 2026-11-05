"""LangChain tools exposed to the orchestrator."""

from __future__ import annotations

from collections.abc import Callable

import duckdb
from langchain_core.tools import StructuredTool

from srag_agent.audit import AuditLogger
from srag_agent.news.models import NewsBatch
from srag_agent.tools.metrics_tools import build_metric_tools
from srag_agent.tools.news_tool import build_news_tool
from srag_agent.tools.sql_tool import build_sql_tool


def build_tools(
    con: duckdb.DuckDBPyConnection,
    audit: AuditLogger,
    news_provider: Callable[[], NewsBatch],
    row_limit: int,
) -> list[StructuredTool]:
    return [
        *build_metric_tools(con, audit),
        build_sql_tool(con, audit, row_limit),
        build_news_tool(news_provider, audit),
    ]


__all__ = ["build_tools"]
