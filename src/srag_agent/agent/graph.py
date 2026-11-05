"""LangGraph orchestrator.

    collect_metrics -> fetch_news -> analyze <-> run_tools -> write_report -> validate -> render
                                                                   ^              |
                                                                   +---- retry ---+
Deterministic nodes never call the LLM; the LLM never computes a number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import duckdb
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from srag_agent.agent import prompts
from srag_agent.agent.llm import invoke_structured, with_tools
from srag_agent.agent.state import AgentState
from srag_agent.audit import AuditLogger
from srag_agent.config import Settings
from srag_agent.guardrails.output_validation import ValidationResult, validate_report
from srag_agent.metrics import collect_metrics
from srag_agent.metrics.base import scope_label
from srag_agent.news import fetch_news, google_news_rss, tavily
from srag_agent.news.models import NewsBatch
from srag_agent.report.models import ReportContent
from srag_agent.report.render import write_report_files
from srag_agent.tools.news_tool import format_news_for_llm

BUDGET_EXHAUSTED = "Orçamento de chamadas de ferramenta esgotado; redija com o que já tem."


@dataclass
class GraphContext:
    """Everything the nodes need that is not part of the state."""

    settings: Settings
    con: duckdb.DuckDBPyConnection
    audit: AuditLogger
    model: BaseChatModel
    tools: list[BaseTool]
    model_name: str
    news: NewsBatch = field(default_factory=NewsBatch)

    @property
    def tool_map(self) -> dict[str, BaseTool]:
        return {tool.name: tool for tool in self.tools}


def build_graph(ctx: GraphContext) -> CompiledStateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("collect_metrics", lambda state: _collect_metrics(ctx, state))
    graph.add_node("fetch_news", lambda state: _fetch_news(ctx, state))
    graph.add_node("analyze", lambda state: _analyze(ctx, state))
    graph.add_node("run_tools", lambda state: _run_tools(ctx, state))
    graph.add_node("write_report", lambda state: _write_report(ctx, state))
    graph.add_node("validate", lambda state: _validate(ctx, state))
    graph.add_node("render", lambda state: _render(ctx, state))

    graph.add_edge(START, "collect_metrics")
    graph.add_edge("collect_metrics", "fetch_news")
    graph.add_edge("fetch_news", "analyze")
    graph.add_conditional_edges("analyze", _after_analyze)
    graph.add_edge("run_tools", "analyze")
    graph.add_edge("write_report", "validate")
    graph.add_conditional_edges("validate", lambda state: _after_validate(ctx, state))
    graph.add_edge("render", END)
    return graph.compile()


# --- deterministic nodes -------------------------------------------------------------------


def _collect_metrics(ctx: GraphContext, state: AgentState) -> AgentState:
    bundle = collect_metrics(ctx.con, state.get("reference_date"), state.get("uf"))
    ctx.audit.log(
        "tool_call",
        "collect_metrics",
        reference_date=bundle.reference_date.isoformat(),
        uf=bundle.uf,
        metrics={m.name: m.value for m in bundle.metrics},
    )
    return {"bundle": bundle, "tool_calls_used": 0, "write_attempts": 0}


def _fetch_news(ctx: GraphContext, state: AgentState) -> AgentState:
    if state.get("include_news", True):
        ctx.news = fetch_news(ctx.settings)
    else:
        ctx.news = NewsBatch(errors=["desativado por --no-news"])
    providers = [google_news_rss.PROVIDER]
    if ctx.settings.has_tavily_key:
        providers.append(tavily.PROVIDER)
    ctx.audit.log(
        "news_fetch",
        "+".join(providers),
        queries=ctx.news.queries,
        items=[{"id": i.id, "source": i.source, "title": i.title} for i in ctx.news.items],
        discarded=[d.model_dump() for d in ctx.news.discarded],
        errors=ctx.news.errors,
    )
    return {"news": ctx.news}


# --- analysis loop (LLM with tools) ----------------------------------------------------------


def _analyze(ctx: GraphContext, state: AgentState) -> AgentState:
    messages = list(state.get("messages") or [])
    if not messages:
        bundle = state["bundle"]
        messages = [
            SystemMessage(content=prompts.SYSTEM_PROMPT),
            HumanMessage(
                content=prompts.ANALYSIS_INSTRUCTIONS.format(
                    max_tool_calls=ctx.settings.max_tool_calls,
                    metrics_json=prompts.metrics_json(bundle),
                    series_summary=prompts.series_summary(bundle),
                    news_block=format_news_for_llm(state["news"]),
                )
            ),
        ]
    calls_left = ctx.settings.max_tool_calls - state.get("tool_calls_used", 0)
    tokens_used = sum(ctx.audit.token_usage())
    if tokens_used > ctx.settings.max_total_tokens:
        ctx.audit.log(
            "guardrail",
            "token_budget",
            passed=False,
            tokens_used=tokens_used,
            limit=ctx.settings.max_total_tokens,
        )
        calls_left = 0
    model = with_tools(ctx.model, ctx.tools if calls_left > 0 else [])
    reply = model.invoke(messages)
    if not isinstance(reply, AIMessage):
        reply = AIMessage(content=str(reply))
    messages.append(reply)
    ctx.audit.log(
        "decision",
        "analyze",
        text=_text(reply),
        tool_calls=[{"name": c["name"], "args": c["args"]} for c in reply.tool_calls],
    )
    return {"messages": messages, "analysis_notes": _text(reply)}


def _after_analyze(state: AgentState) -> Literal["run_tools", "write_report"]:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "run_tools"
    return "write_report"


def _run_tools(ctx: GraphContext, state: AgentState) -> AgentState:
    messages = list(state["messages"])
    last = messages[-1]
    requested = last.tool_calls if isinstance(last, AIMessage) else []
    used = state.get("tool_calls_used", 0)
    for call in requested:
        if used >= ctx.settings.max_tool_calls:
            content = BUDGET_EXHAUSTED
            ctx.audit.log("guardrail", "tool_budget", passed=False, tool=call["name"])
        else:
            content = _invoke_tool(ctx, call["name"], call["args"])
            used += 1
        messages.append(ToolMessage(content=content, tool_call_id=call["id"] or call["name"]))
    return {"messages": messages, "tool_calls_used": used}


def _invoke_tool(ctx: GraphContext, name: str, args: dict[str, Any]) -> str:
    tool = ctx.tool_map.get(name)
    if tool is None:
        ctx.audit.log("error", name, where="run_tools", error="unknown tool")
        return f"ERRO: ferramenta desconhecida '{name}'."
    try:
        return str(tool.invoke(args))
    except Exception as error:  # noqa: BLE001 - the model must see validation errors
        ctx.audit.log("error", name, where="run_tools", error=f"{type(error).__name__}: {error}")
        return f"ERRO ao chamar {name}: {type(error).__name__}: {error}"


# --- writing, validation, rendering ----------------------------------------------------------


def _write_report(ctx: GraphContext, state: AgentState) -> AgentState:
    bundle = state["bundle"]
    messages = [
        SystemMessage(content=prompts.SYSTEM_PROMPT),
        HumanMessage(
            content=prompts.WRITE_INSTRUCTIONS.format(
                feedback=prompts.feedback_block(state.get("validation_feedback", "")),
                reference_date=bundle.reference_date.isoformat(),
                scope=scope_label(bundle.uf),
                latest_case_date=bundle.latest_case_date.isoformat(),
                metrics_json=prompts.metrics_json(bundle),
                analysis_notes=state.get("analysis_notes") or "(nenhum)",
                news_block=format_news_for_llm(state["news"]),
            )
        ),
    ]
    attempts = state.get("write_attempts", 0) + 1
    try:
        draft = invoke_structured(ctx.model, messages, ReportContent)
    except Exception as error:  # noqa: BLE001 - recorded and retried by the validate edge
        ctx.audit.log("error", "write_report", where="structured_output", error=str(error)[:500])
        return {
            "draft": None,
            "write_attempts": attempts,
            "validation_feedback": f"A saída anterior não seguiu o esquema: {error}"[:800],
        }
    ctx.audit.log(
        "decision",
        "write_report",
        attempt=attempts,
        cited_news=[r.model_dump() for r in draft.cited_news],
        limitations=draft.limitations,
    )
    return {"draft": draft, "write_attempts": attempts}


def _validate(ctx: GraphContext, state: AgentState) -> AgentState:
    draft = state.get("draft")
    if draft is None:
        result = ValidationResult(passed=False, issues=["Sem rascunho válido"])
    else:
        tool_outputs = [
            str(m.content) for m in state.get("messages") or [] if isinstance(m, ToolMessage)
        ]
        result = validate_report(draft, state["bundle"], state["news"], ctx.audit, tool_outputs)
    ctx.audit.log(
        "guardrail",
        "output_validation",
        passed=result.passed,
        attempt=state.get("write_attempts", 0),
        checks=result.checks,
        issues=result.issues,
    )
    feedback = "\n".join(f"- {issue}" for issue in result.issues)
    return {"validation": result, "validation_feedback": feedback}


def _after_validate(ctx: GraphContext, state: AgentState) -> Literal["write_report", "render"]:
    validation = state.get("validation")
    if validation is not None and validation.passed:
        return "render"
    if state.get("write_attempts", 0) < ctx.settings.max_write_attempts:
        return "write_report"
    ctx.audit.log("guardrail", "max_write_attempts", passed=False, attempts=state["write_attempts"])
    return "render"


def _render(ctx: GraphContext, state: AgentState) -> AgentState:
    report_path, chart_paths = write_report_files(ctx, state)
    return {"report_path": report_path, "chart_paths": chart_paths}


def _text(message: AIMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "\n".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )
