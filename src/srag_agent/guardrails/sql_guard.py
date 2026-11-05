"""Guardrail for LLM-written SQL: one read-only SELECT over whitelisted relations.

Defence in depth: (1) DuckDB's own parser must see exactly one SELECT statement,
(2) a keyword blocklist rejects anything that could read files, change settings or
mutate data, (3) every relation referenced must be in the whitelist, (4) the query is
wrapped in an outer LIMIT, (5) the connection is read-only with external access disabled
and (6) execution is interrupted after a timeout (see `tools/sql_tool.py`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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
_RELATION_REFERENCE = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w.]*)", re.IGNORECASE)
_CTE_NAME = re.compile(r"(?:\bWITH\b|,)\s*([A-Za-z_]\w*)\s+AS\s*\(", re.IGNORECASE)
_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)


class SqlRejected(ValueError):
    """Raised when a query violates the guardrail; the message is safe to show the LLM."""


@dataclass(frozen=True)
class GuardedSql:
    original: str
    executable: str
    relations: tuple[str, ...]
    row_limit: int


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


def _referenced_relations(sql: str) -> tuple[str, ...]:
    cte_names = {name.lower() for name in _CTE_NAME.findall(sql)}
    found = []
    for raw in _RELATION_REFERENCE.findall(sql):
        name = raw.lower().split(".")[-1]
        if name not in cte_names:
            found.append(name)
    return tuple(dict.fromkeys(found))


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
    return GuardedSql(original=sql, executable=executable, relations=relations, row_limit=row_limit)
