"""DuckDB access: database build from the processed Parquet and read-only queries."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import duckdb

from srag_agent.data import schema

CASES_TABLE = "cases"
QUERYABLE_RELATIONS: tuple[str, ...] = (
    CASES_TABLE,
    "daily_cases",
    "monthly_cases",
    "cases_by_uf",
)
"""Relations the guarded SQL tool may reference (table plus aggregated views)."""

_VIEWS: dict[str, str] = {
    "daily_cases": f"""
        SELECT dt_sin_pri AS case_date, count(*) AS cases
        FROM {CASES_TABLE}
        WHERE dt_sin_pri IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """,
    "monthly_cases": f"""
        SELECT date_trunc('month', dt_sin_pri)::DATE AS month, count(*) AS cases
        FROM {CASES_TABLE}
        WHERE dt_sin_pri IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """,
    "cases_by_uf": f"""
        SELECT
            sg_uf_not AS uf,
            count(*) AS cases,
            count(*) FILTER (WHERE evolucao = 2) AS deaths,
            count(*) FILTER (WHERE uti = 1) AS icu_admissions
        FROM {CASES_TABLE}
        GROUP BY 1
        ORDER BY 1
    """,
}


def _cases_select(parquet_path: Path) -> str:
    """SELECT that loads the Parquet with episode and vaccine dates cast to DATE."""
    date_columns = {c.lower() for c in (*schema.EVENT_DATE_COLUMNS, *schema.VACCINE_DATE_COLUMNS)}
    projections = [
        f"CAST({column} AS DATE) AS {column}" if column in date_columns else column
        for column in schema.PROCESSED_COLUMNS
    ]
    return f"SELECT {', '.join(projections)} FROM read_parquet('{parquet_path.as_posix()}')"


def build_database(parquet_path: Path, db_path: Path) -> None:
    """(Re)create the DuckDB file with the `cases` table and aggregated views."""
    if db_path.exists():
        db_path.unlink()
    wal = db_path.with_suffix(db_path.suffix + ".wal")
    if wal.exists():
        wal.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as con:
        con.execute(f"CREATE TABLE {CASES_TABLE} AS {_cases_select(parquet_path)}")
        for name, body in _VIEWS.items():
            con.execute(f"CREATE VIEW {name} AS {body}")


def ensure_database(parquet_path: Path, db_path: Path) -> Path:
    """Build the DuckDB file when missing or older than the Parquet it derives from."""
    if not parquet_path.exists():
        msg = (
            f"Processed dataset not found at {parquet_path}. "
            "Run `uv run python scripts/build_dataset.py` first."
        )
        raise FileNotFoundError(msg)
    stale = not db_path.exists() or db_path.stat().st_mtime < parquet_path.stat().st_mtime
    if stale:
        build_database(parquet_path, db_path)
    return db_path


def open_readonly(db_path: Path) -> duckdb.DuckDBPyConnection:
    """Open the database for reading only, with file-system access disabled at the engine
    level, so that the agent never gets a writable handle nor a way to read local files.
    """
    return duckdb.connect(str(db_path), read_only=True, config={"enable_external_access": "false"})


def fetch_all(
    con: duckdb.DuckDBPyConnection, sql: str, params: Sequence[Any] | None = None
) -> list[dict[str, Any]]:
    """Run a parametrised query and return rows as dictionaries."""
    cursor = con.execute(sql, list(params or []))
    columns = [description[0] for description in cursor.description or []]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def fetch_one(
    con: duckdb.DuckDBPyConnection, sql: str, params: Sequence[Any] | None = None
) -> dict[str, Any]:
    """Run a query expected to return exactly one row."""
    rows = fetch_all(con, sql, params)
    if len(rows) != 1:
        msg = f"Expected exactly one row, got {len(rows)}"
        raise ValueError(msg)
    return rows[0]


def file_sha256(path: Path) -> str:
    """Hex digest of a file, used to pin the dataset version in audit logs and reports."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
