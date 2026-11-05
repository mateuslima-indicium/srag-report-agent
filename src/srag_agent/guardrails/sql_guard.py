"""Guardrail for LLM-written SQL: one read-only SELECT over whitelisted relations.

Defence in depth: (1) DuckDB's own parser must see exactly one SELECT statement,
(2) a keyword blocklist rejects anything that could read files, change settings or
mutate data, (3) every relation in the parsed AST must be in the whitelist and table
functions are refused, (4) queries over row-level relations must aggregate, so the model
never receives one person's record, (5) the query is wrapped in an outer LIMIT, (6) the
connection is read-only with external access disabled and (7) execution is interrupted
after a timeout (see `tools/sql_tool.py`).
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


def _referenced_relations(sql: str) -> tuple[tuple[str, ...], dict[str, Any]]:
    """Every base table the statement reads, anywhere in the AST (joins, subqueries, CTEs),
    plus the parsed AST itself.

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
    return tuple(dict.fromkeys(tables)), ast


# --- aggregate-only rule for row-level relations ----------------------------------------------

AGGREGATE_FUNCTIONS = frozenset(
    {
        "count",
        "count_star",
        "count_if",
        "sum",
        "avg",
        "mean",
        "min",
        "max",
        "median",
        "mode",
        "quantile",
        "quantile_cont",
        "quantile_disc",
        "stddev",
        "stddev_pop",
        "stddev_samp",
        "variance",
        "var_pop",
        "var_samp",
        "approx_count_distinct",
        "approx_quantile",
        "any_value",
        "arg_min",
        "arg_max",
        "min_by",
        "max_by",
        "bool_and",
        "bool_or",
        "histogram",
        "entropy",
        "corr",
        "covar_pop",
        "covar_samp",
        "product",
    }
)
"""Function names whose result summarises many rows (the binder accepts no others here)."""


def _ctes(node: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(entry.get("key", "")).lower(): entry.get("value", {}).get("query_node", {})
        for entry in node.get("cte_map", {}).get("map", [])
    }


def _expression_is_aggregate(expr: Any, ctes: dict[str, Any], row_level: tuple[str, ...]) -> bool:
    """True when the expression cannot expose a single row's value."""
    if isinstance(expr, list):
        return all(_expression_is_aggregate(item, ctes, row_level) for item in expr)
    if not isinstance(expr, dict):
        return True
    kind = expr.get("class")
    if kind == "FUNCTION":
        if str(expr.get("function_name", "")).lower() in AGGREGATE_FUNCTIONS:
            return True
        return _expression_is_aggregate(expr.get("children", []), ctes, row_level)
    if kind == "SUBQUERY":
        return _node_is_aggregate(expr.get("subquery", {}).get("node", {}), ctes, row_level)
    if kind in {"COLUMN_REF", "STAR", "WINDOW"}:
        return False
    if kind == "CONSTANT":
        return True
    children = [value for key, value in expr.items() if key not in {"class", "type", "alias"}]
    return _expression_is_aggregate(children, ctes, row_level)


def _from_reads_rows(table: Any, ctes: dict[str, Any], row_level: tuple[str, ...]) -> bool:
    """Does this FROM clause expose individual rows of a row-level relation?"""
    if not isinstance(table, dict):
        return False
    kind = table.get("type")
    if kind == "BASE_TABLE":
        name = str(table.get("table_name", "")).lower()
        if name in ctes:
            return not _node_is_aggregate(ctes[name], ctes, row_level)
        return name in row_level
    if kind == "SUBQUERY":
        return not _node_is_aggregate(table.get("subquery", {}).get("node", {}), ctes, row_level)
    if kind == "JOIN":
        return _from_reads_rows(table.get("left"), ctes, row_level) or _from_reads_rows(
            table.get("right"), ctes, row_level
        )
    return False


def _node_is_aggregate(
    node: dict[str, Any], ctes: dict[str, Any], row_level: tuple[str, ...]
) -> bool:
    """A query node is aggregate when every output row summarises many input rows."""
    if not isinstance(node, dict):
        return False
    scoped = {**ctes, **_ctes(node)}
    if node.get("type") == "SET_OPERATION_NODE":
        sides = node.get("children") or [node.get("left"), node.get("right")]
        return all(_node_is_aggregate(side, scoped, row_level) for side in sides if side)
    if node.get("type") != "SELECT_NODE":
        return False
    if node.get("group_expressions"):
        return True
    if any(m.get("type") == "DISTINCT_MODIFIER" for m in node.get("modifiers", [])):
        return True
    if not _from_reads_rows(node.get("from_table"), scoped, row_level):
        return True
    return _expression_is_aggregate(node.get("select_list", []), scoped, row_level)


def _check_aggregate_only(ast: dict[str, Any], row_level: tuple[str, ...]) -> None:
    statements = ast.get("statements", [])
    node = statements[0].get("node", {}) if statements else {}
    if not _node_is_aggregate(node, {}, row_level):
        msg = (
            f"Consultas sobre {', '.join(row_level)} precisam devolver agregados (GROUP BY, "
            "DISTINCT ou funções como count/sum/avg): linhas individuais não são expostas ao "
            "modelo. Para listas prontas use as views agregadas."
        )
        raise SqlRejected(msg)


def guard_sql(
    sql: str,
    allowed_relations: tuple[str, ...],
    row_limit: int,
    row_level_relations: tuple[str, ...] = (),
) -> GuardedSql:
    """Validate `sql` and return the wrapped, limited query that may be executed.

    `row_level_relations` lists relations whose rows describe one person each; queries that
    read them must aggregate, so that the model only ever sees counts and ratios.
    """
    if not sql or not sql.strip():
        raise SqlRejected("Consulta vazia.")
    cleaned = _strip_comments(sql)
    statement = _single_select(cleaned)
    _check_blocklist(statement)
    relations, ast = _referenced_relations(statement)
    if not relations:
        raise SqlRejected("A consulta precisa ler ao menos uma tabela/view permitida.")
    unknown = [name for name in relations if name not in allowed_relations]
    if unknown:
        msg = (
            f"Relação não permitida: {', '.join(unknown)}. "
            f"Use apenas: {', '.join(allowed_relations)}."
        )
        raise SqlRejected(msg)
    if row_level_relations:
        _check_aggregate_only(ast, row_level_relations)
    executable = f"SELECT * FROM ({statement}) AS guarded LIMIT {int(row_limit)}"
    return GuardedSql(executable=executable, relations=relations)
