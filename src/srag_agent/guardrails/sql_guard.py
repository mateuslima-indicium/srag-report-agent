"""Guardrail for LLM-written SQL: one read-only SELECT over whitelisted relations.

Defence in depth: (1) DuckDB's own parser must see exactly one SELECT statement,
(2) a keyword blocklist rejects anything that could read files, change settings or
mutate data, (3) every relation in the parsed AST must be in the whitelist and table
functions are refused, (4) the query is wrapped in an outer LIMIT, (5) the connection is
read-only with external access disabled and (6) execution is interrupted after a timeout
(see `tools/sql_tool.py`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import cache
from typing import Any

import duckdb

BLOCKED_KEYWORDS = re.compile(
    r"\b("
    r"ATTACH|DETACH|COPY|PRAGMA|INSTALL|LOAD|CREATE|INSERT|UPDATE|DELETE|DROP|ALTER|"
    r"EXPORT|IMPORT|CALL|SET|RESET|PREPARE|EXECUTE|VACUUM|CHECKPOINT|TRUNCATE|MERGE|"
    r"read_csv\w*|read_parquet|read_json\w*|read_text|read_blob|glob|sniff_csv|"
    r"parquet_\w+|duckdb_\w+|pg_\w+|sqlite_\w+|information_schema|getenv|current_setting"
    r")\b",
    re.IGNORECASE,
)
_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)


class SqlRejected(ValueError):
    """Raised when a query violates the guardrail; the message is safe to show the LLM."""


@dataclass(frozen=True)
class GuardedSql:
    executable: str
    relations: tuple[str, ...]


@dataclass
class _Relations:
    """Tables, table functions and CTE names found while walking the parsed AST."""

    tables: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    ctes: set[str] = field(default_factory=set)


@cache
def _parser() -> duckdb.DuckDBPyConnection:
    """In-memory connection used only to serialise the AST (no catalog, no file access)."""
    return duckdb.connect(":memory:", config={"enable_external_access": "false"})


def _strip_comments(sql: str) -> str:
    return _COMMENT.sub(" ", sql)


def _single_select(sql: str) -> str:
    try:
        statements = duckdb.extract_statements(sql)
    except duckdb.Error as error:
        msg = f"SQL inválido: {str(error).splitlines()[0]}"
        raise SqlRejected(msg) from error
    if len(statements) != 1:
        msg = f"Apenas uma instrução é permitida; recebi {len(statements)}."
        raise SqlRejected(msg)
    if statements[0].type != duckdb.StatementType.SELECT:
        msg = f"Apenas SELECT é permitido; recebi {statements[0].type.name}."
        raise SqlRejected(msg)
    return sql.strip().rstrip(";").strip()


def _check_blocklist(sql: str) -> None:
    match = BLOCKED_KEYWORDS.search(sql)
    if match:
        msg = f"Palavra-chave bloqueada: {match.group(0)}."
        raise SqlRejected(msg)


def _walk(node: Any, found: _Relations) -> None:
    if isinstance(node, dict):
        if node.get("type") == "BASE_TABLE":
            found.tables.append(str(node.get("table_name", "")).lower())
        elif node.get("type") == "TABLE_FUNCTION":
            found.functions.append(str(node["function"].get("function_name", "")).lower())
        for entry in node.get("cte_map", {}).get("map", []):
            found.ctes.add(str(entry.get("key", "")).lower())
        for value in node.values():
            _walk(value, found)
    elif isinstance(node, list):
        for value in node:
            _walk(value, found)


def _referenced_relations(sql: str) -> tuple[str, ...]:
    """Every base table the statement reads, anywhere in the AST (joins, subqueries, CTEs).

    Table functions (`range()`, `pragma_*()`, `read_*()`) are refused outright: the agent
    only needs the whitelisted table and views.
    """
    row = _parser().execute("SELECT json_serialize_sql(?)", [sql]).fetchone()
    ast = json.loads(row[0] if row else "{}")
    if ast.get("error"):
        msg = f"SQL inválido: {ast.get('error_message', 'não foi possível analisar')}"
        raise SqlRejected(msg)
    found = _Relations()
    _walk(ast.get("statements", []), found)
    if found.functions:
        msg = f"Funções de tabela não são permitidas: {', '.join(found.functions)}."
        raise SqlRejected(msg)
    tables = [name for name in found.tables if name not in found.ctes]
    return tuple(dict.fromkeys(tables))


def guard_sql(sql: str, allowed_relations: tuple[str, ...], row_limit: int) -> GuardedSql:
    """Validate `sql` and return the wrapped, limited query that may be executed."""
    if not sql or not sql.strip():
        raise SqlRejected("Consulta vazia.")
    cleaned = _strip_comments(sql)
    statement = _single_select(cleaned)
    _check_blocklist(statement)
    relations = _referenced_relations(statement)
    if not relations:
        raise SqlRejected("A consulta precisa ler ao menos uma tabela/view permitida.")
    unknown = [name for name in relations if name not in allowed_relations]
    if unknown:
        msg = (
            f"Relação não permitida: {', '.join(unknown)}. "
            f"Use apenas: {', '.join(allowed_relations)}."
        )
        raise SqlRejected(msg)
    executable = f"SELECT * FROM ({statement}) AS guarded LIMIT {int(row_limit)}"
    return GuardedSql(executable=executable, relations=relations)
