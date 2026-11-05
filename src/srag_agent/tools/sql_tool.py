"""`run_readonly_sql`: guarded ad-hoc SQL for the orchestrator."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import duckdb
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from srag_agent.audit import AuditLogger
from srag_agent.data import schema
from srag_agent.data.db import QUERYABLE_RELATIONS
from srag_agent.guardrails.sql_guard import SqlRejected, guard_sql

SQL_TIMEOUT_SECONDS = 15.0
MAX_RESULT_CHARS = 6000


class SqlInput(BaseModel):
    sql: str = Field(
        description=(
            "Um único SELECT sobre as relações `cases`, `daily_cases`, `monthly_cases` ou "
            "`cases_by_uf`. Sem DDL/DML, sem funções de arquivo. O resultado é limitado."
        )
    )
    purpose: str = Field(
        description="Por que esta consulta ajuda o relatório (vai para a auditoria)."
    )


def execute_with_timeout(
    con: duckdb.DuckDBPyConnection, sql: str, timeout_seconds: float
) -> tuple[list[str], list[tuple[Any, ...]]]:
    """Run `sql`, interrupting the connection if it exceeds the timeout."""
    timer = threading.Timer(timeout_seconds, con.interrupt)
    timer.start()
    try:
        cursor = con.execute(sql)
        columns = [description[0] for description in cursor.description or []]
        return columns, cursor.fetchall()
    finally:
        timer.cancel()


def _serialise(columns: list[str], rows: list[tuple[Any, ...]]) -> str:
    """JSON payload for the model, halving the rows until it fits `MAX_RESULT_CHARS`."""
    safe_rows = [[_json_safe(v) for v in row] for row in rows]
    payload: dict[str, Any] = {"columns": columns, "rows": safe_rows}
    text = json.dumps(payload, ensure_ascii=False, default=str)
    while len(text) > MAX_RESULT_CHARS and len(payload["rows"]) > 1:
        payload["rows"] = payload["rows"][: len(payload["rows"]) // 2]
        payload["truncated"] = True
        text = json.dumps(payload, ensure_ascii=False, default=str)
    return text


def _json_safe(value: Any) -> Any:
    return value if isinstance(value, int | float | str | bool | None) else str(value)


def build_sql_tool(
    con: duckdb.DuckDBPyConnection, audit: AuditLogger, row_limit: int
) -> StructuredTool:
    def run_readonly_sql(sql: str, purpose: str) -> str:
        started = time.perf_counter()
        try:
            guarded = guard_sql(sql, QUERYABLE_RELATIONS, row_limit)
        except SqlRejected as rejection:
            audit.log("guardrail", "sql_guard", passed=False, sql=sql, reason=str(rejection))
            return f"CONSULTA REJEITADA pelo guardrail de SQL: {rejection}"
        audit.log("guardrail", "sql_guard", passed=True, sql=sql, relations=list(guarded.relations))
        try:
            columns, rows = execute_with_timeout(con, guarded.executable, SQL_TIMEOUT_SECONDS)
        except duckdb.Error as error:
            reason = str(error).splitlines()[0]
            audit.log("tool_call", "run_readonly_sql", purpose=purpose, sql=sql, error=reason)
            return f"ERRO ao executar a consulta: {reason}"
        audit.log(
            "tool_call",
            "run_readonly_sql",
            purpose=purpose,
            sql=sql,
            rows=len(rows),
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return _serialise(columns, rows)

    return StructuredTool.from_function(
        func=run_readonly_sql,
        name="run_readonly_sql",
        description=tool_description(),
        args_schema=SqlInput,
    )


def tool_description() -> str:
    """Schema summary for the LLM, derived from the data contract (never hand-maintained)."""
    columns = ", ".join(schema.PROCESSED_COLUMNS)
    codes = "; ".join(
        f"{column} " + " ".join(f"{code}={label}" for code, label in labels.items())
        for column, labels in schema.CODE_LABELS.items()
    )
    return (
        "Executa um SELECT somente leitura no banco de casos de SRAG para aprofundar a "
        "análise (ex.: por UF, faixa etária, sexo, classificação final). Tabela `cases` "
        f"(colunas: {columns}) e views {', '.join(f'`{r}`' for r in QUERYABLE_RELATIONS[1:])}. "
        f"Códigos: {codes}. Datas em DATE; age_band em faixas de 10 anos; sg_uf_not é a UF. "
        "Prefira consultas agregadas; o resultado é limitado a poucas linhas."
    )
