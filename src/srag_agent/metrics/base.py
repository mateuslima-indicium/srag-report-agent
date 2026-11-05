"""Shared helpers: reference-date resolution, windows and filtered counts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import duckdb

from srag_agent.data import schema
from srag_agent.data.db import CASES_TABLE, fetch_one

PRELIMINARY_DAYS = 14
"""Days before the latest symptom-onset date considered under-reported."""

DEFAULT_WINDOW_DAYS = 30
GROWTH_WINDOWS = (7, 30)
"""Comparison windows of the case-growth metric (both are always computed)."""

RATE_WINDOWS = (7, 30, 60, 90)
"""Windows the model may request for the mortality, ICU and vaccination tools."""


@dataclass(frozen=True)
class Window:
    """Closed date interval `[start, end]`."""

    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def window_ending(end: date, days: int) -> Window:
    return Window(start=end - timedelta(days=days - 1), end=end)


def previous_window(window: Window) -> Window:
    return window_ending(window.start - timedelta(days=1), window.days)


def latest_case_date(con: duckdb.DuckDBPyConnection) -> date:
    row = fetch_one(con, f"SELECT max(dt_sin_pri) AS latest FROM {CASES_TABLE}")
    if row["latest"] is None:
        msg = "The cases table is empty"
        raise ValueError(msg)
    return row["latest"]


def preliminary_cutoff(con: duckdb.DuckDBPyConnection) -> date:
    """Dates after the cutoff are still being reported (relative to the data, not to today)."""
    return latest_case_date(con) - timedelta(days=PRELIMINARY_DAYS)


def resolve_reference_date(con: duckdb.DuckDBPyConnection, requested: date | None) -> date:
    """Default to the latest symptom-onset date so that reporting lag is not read as a drop."""
    latest = latest_case_date(con)
    if requested is None:
        return latest
    if requested > latest:
        msg = (
            f"Data de referência {requested} é posterior ao último caso do banco ({latest}). "
            "Use uma data até essa."
        )
        raise ValueError(msg)
    return requested


def validate_uf(uf: str | None) -> str | None:
    """Error messages are in Portuguese: they reach the CLI user and the model as they are."""
    if uf is None:
        return None
    normalised = uf.strip().upper()
    if normalised not in schema.BRAZIL_UFS:
        msg = f"UF desconhecida {uf!r}; use uma de: {', '.join(schema.BRAZIL_UFS)}"
        raise ValueError(msg)
    return normalised


def uf_clause(uf: str | None) -> tuple[str, list[Any]]:
    """SQL fragment (always starting with AND) and its parameters for an optional UF filter."""
    if uf is None:
        return "", []
    return " AND sg_uf_not = ?", [uf]


def count_cases(
    con: duckdb.DuckDBPyConnection,
    window: Window,
    uf: str | None,
    extra_condition: str = "",
) -> int:
    """Count cases whose symptom onset falls inside `window`, with optional extra SQL."""
    clause, params = uf_clause(uf)
    sql = (
        f"SELECT count(*) AS n FROM {CASES_TABLE} "
        f"WHERE dt_sin_pri BETWEEN ? AND ?{clause}{extra_condition}"
    )
    return int(fetch_one(con, sql, [window.start, window.end, *params])["n"])


def ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def uf_suffix(uf: str | None) -> str:
    return f" na UF {uf}" if uf else " no Brasil"


def scope_label(uf: str | None) -> str:
    """`UF SP` or `Brasil`, as shown in titles, charts and the CLI."""
    return f"UF {uf}" if uf else "Brasil"
