"""Accepted and rejected SQL for the guardrail (execution through the tool is in test_tools)."""

from __future__ import annotations

import pytest

from srag_agent.data.db import QUERYABLE_RELATIONS
from srag_agent.guardrails.sql_guard import SqlRejected, guard_sql

ACCEPTED = [
    "SELECT count(*) FROM cases",
    "select sg_uf_not, count(*) from cases group by 1 order by 2 desc",
    "SELECT * FROM daily_cases",
    "SELECT month, cases FROM monthly_cases WHERE month >= DATE '2026-01-01'",
    "SELECT uf, deaths FROM cases_by_uf ORDER BY deaths DESC LIMIT 5",
    "SELECT age_band, count(*) FILTER (WHERE evolucao = 2) AS deaths FROM cases GROUP BY 1",
    "WITH recent AS (SELECT * FROM cases WHERE dt_sin_pri >= DATE '2026-10-01') "
    "SELECT uti, count(*) FROM recent GROUP BY 1",
    "SELECT a.uf, b.cases FROM cases_by_uf a JOIN cases_by_uf b ON a.uf = b.uf",
    "SELECT * FROM (SELECT sg_uf_not FROM cases) sub",
    "SELECT count(*) FROM cases; ",
    "-- comentário\nSELECT count(*) FROM cases",
    "SELECT classi_fin, avg(age_years) FROM cases WHERE classi_fin IN (1, 5) GROUP BY 1",
    "SELECT count(*) FROM main.cases",
    "SELECT * FROM cases /* comments are stripped, so this DROP TABLE is inert */",
    "SELECT c.uti, d.cases FROM cases c, daily_cases d WHERE c.dt_sin_pri = d.case_date",
]

REJECTED = [
    ("", "vazia"),
    ("   ", "vazia"),
    ("DELETE FROM cases", "Apenas SELECT"),
    ("DROP TABLE cases", "Apenas SELECT"),
    ("UPDATE cases SET uti = 1", "Apenas SELECT"),
    ("INSERT INTO cases SELECT * FROM cases", "Apenas SELECT"),
    ("CREATE TABLE x AS SELECT 1", "Apenas SELECT"),
    ("SELECT 1; SELECT 2", "Apenas uma instrução"),
    ("SELECT count(*) FROM cases; DROP TABLE cases", "Apenas uma instrução"),
    ("ATTACH 'other.db' AS other", "Apenas SELECT"),
    ("PRAGMA database_list", "Apenas SELECT"),
    ("INSTALL httpfs", "Apenas SELECT"),
    ("COPY cases TO 'out.csv'", "Apenas SELECT"),
    ("SET memory_limit = '1GB'", "Apenas SELECT"),
    ("SELECT * FROM read_csv('C:/Windows/win.ini')", "bloqueada"),
    ("SELECT * FROM read_parquet('data/processed/srag.parquet')", "bloqueada"),
    ("SELECT * FROM glob('*')", "bloqueada"),
    ("SELECT * FROM duckdb_settings()", "bloqueada"),
    ("SELECT * FROM information_schema.tables", "bloqueada"),
    ("SELECT current_setting('home_directory')", "bloqueada"),
    ("SELECT * FROM secrets", "Relação não permitida"),
    ("SELECT * FROM cases c JOIN patients p ON 1=1", "Relação não permitida"),
    ("SELECT 1", "ao menos uma tabela"),
    ("SELECT count(*) FROM cases WHERE x = (SELECT 1 FROM other)", "Relação não permitida"),
    ("SELEC count(*) FROM cases", "SQL inválido"),
    ("WITH x AS (DELETE FROM cases) SELECT 1", "bloqueada: DELETE"),
    # relations reachable without FROM/JOIN keywords: comma joins and table functions
    ("SELECT * FROM cases, patients", "Relação não permitida: patients"),
    ("SELECT * FROM cases, pragma_version()", "Funções de tabela"),
    ("SELECT * FROM cases CROSS JOIN range(3)", "Funções de tabela"),
    ("SELECT * FROM cases WHERE uti IN (SELECT 1 FROM pragma_database_list())", "Funções"),
    ("SELECT * FROM 'C:/Windows/win.ini'", "Relação não permitida"),
    ("SELECT * FROM cases, 'C:/Windows/win.ini'", "Relação não permitida"),
]


@pytest.mark.parametrize("sql", ACCEPTED)
def test_accepted_queries_are_wrapped_with_limit(sql: str) -> None:
    guarded = guard_sql(sql, QUERYABLE_RELATIONS, row_limit=50)
    assert guarded.executable.startswith("SELECT * FROM (")
    assert guarded.executable.endswith("LIMIT 50")
    assert guarded.relations
    assert set(guarded.relations) <= set(QUERYABLE_RELATIONS)


@pytest.mark.parametrize(("sql", "reason"), REJECTED)
def test_rejected_queries(sql: str, reason: str) -> None:
    with pytest.raises(SqlRejected, match=reason):
        guard_sql(sql, QUERYABLE_RELATIONS, row_limit=50)


AGGREGATED = [
    "SELECT count(*) FROM cases",
    "SELECT sg_uf_not, count(*) AS n FROM cases GROUP BY 1 ORDER BY n DESC",
    "SELECT DISTINCT sg_uf_not FROM cases",
    "SELECT round(100.0 * sum(CASE WHEN uti = 1 THEN 1 ELSE 0 END) / count(*), 1) FROM cases",
    "SELECT * FROM (SELECT age_band, count(*) AS n FROM cases GROUP BY 1) s ORDER BY n",
    "WITH r AS (SELECT * FROM cases WHERE uti = 1) SELECT uti, count(*) FROM r GROUP BY 1",
    "SELECT count(*) FROM cases UNION ALL SELECT count(*) FROM cases",
    "SELECT * FROM daily_cases",
    "SELECT * FROM cases_by_uf ORDER BY deaths DESC LIMIT 5",
    "SELECT c.sg_uf_not, count(*) FROM cases c JOIN cases_by_uf u ON u.uf = c.sg_uf_not GROUP BY 1",
    "SELECT (SELECT count(*) FROM cases) AS n",
    "SELECT min(dt_sin_pri), max(dt_sin_pri) FROM cases WHERE sg_uf_not = 'AM'",
]

ROW_LEVEL = [
    "SELECT * FROM cases",
    "SELECT sg_uf_not FROM cases LIMIT 1",
    "SELECT dt_sin_pri, age_years FROM cases WHERE age_years < 1",
    "SELECT * FROM (SELECT * FROM cases) s",
    "WITH r AS (SELECT * FROM cases) SELECT * FROM r",
    "SELECT count(*) OVER () FROM cases",
    "SELECT count(*) FROM cases UNION ALL SELECT uti FROM cases",
    "SELECT c.*, u.deaths FROM cases c JOIN cases_by_uf u ON u.uf = c.sg_uf_not",
    "SELECT count(*), sg_uf_not FROM cases",
    "SELECT age_years, (SELECT count(*) FROM cases) FROM cases",
]


@pytest.mark.parametrize("sql", AGGREGATED)
def test_aggregated_queries_may_read_the_cases_table(sql: str) -> None:
    assert guard_sql(sql, QUERYABLE_RELATIONS, 50, row_level_relations=("cases",)).relations


@pytest.mark.parametrize("sql", ROW_LEVEL)
def test_row_level_queries_over_cases_are_refused(sql: str) -> None:
    with pytest.raises(SqlRejected, match="precisam devolver agregados"):
        guard_sql(sql, QUERYABLE_RELATIONS, 50, row_level_relations=("cases",))
    # the same statement is fine when no relation is declared row-level
    assert guard_sql(sql, QUERYABLE_RELATIONS, 50).relations


def test_cte_names_are_not_treated_as_tables() -> None:
    sql = "WITH a AS (SELECT * FROM cases), b AS (SELECT * FROM a) SELECT count(*) FROM b"
    assert guard_sql(sql, QUERYABLE_RELATIONS, 10).relations == ("cases",)


def test_relations_are_found_in_every_clause() -> None:
    sql = (
        "SELECT * FROM cases c LEFT JOIN LATERAL "
        "(SELECT 1 FROM daily_cases d WHERE d.cases > c.uti) x ON true, monthly_cases m"
    )
    assert guard_sql(sql, QUERYABLE_RELATIONS, 10).relations == (
        "cases",
        "daily_cases",
        "monthly_cases",
    )
