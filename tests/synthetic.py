"""Deterministic synthetic dataset whose metric values are known by construction.

Reference date: 2026-10-31 (the latest symptom onset). Layout, all in UF `SP` unless noted:

* previous 30-day window (2026-09-02 .. 2026-10-01): 2 cases/day in UF `MG` -> 60 cases
* days 2026-10-02 .. 2026-10-24 (23 days): 3 cases/day -> 69 cases
* days 2026-10-25 .. 2026-10-31 (7 days): 4 cases/day -> 28 cases
* one extra case on the 15th of every month from 2025-09 to 2026-08 (12 months) in UF `RJ`

Last-30-day cases (97) carry attributes assigned by position so that the rates are:
mortality 10/85, ICU 20/90, covid vaccination 30/90, flu vaccination 40/90.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from srag_agent.data import schema
from srag_agent.data.db import build_database

REFERENCE_DATE = date(2026, 10, 31)
PRELIMINARY_CUTOFF = date(2026, 10, 17)


def _attribute(index: int, counts: list[tuple[int, int | None]]) -> int | None:
    """Pick the code for row `index` from `[(code, how_many), ...]` blocks."""
    offset = 0
    for code, how_many in counts:
        assert how_many is not None
        if index < offset + how_many:
            return code
        offset += how_many
    return None


def synthetic_cases() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for day_offset in range(30):
        day = date(2026, 9, 2) + timedelta(days=day_offset)
        rows += [_row(day, "MG", 1, 1, 2, 2, 2) for _ in range(2)]
    recent: list[date] = []
    for day_offset in range(23):
        recent += [date(2026, 10, 2) + timedelta(days=day_offset)] * 3
    for day_offset in range(7):
        recent += [date(2026, 10, 25) + timedelta(days=day_offset)] * 4
    for index, day in enumerate(recent):
        rows.append(
            _row(
                day,
                "SP",
                evolucao=_attribute(index, [(2, 10), (1, 70), (3, 5), (9, 2), (None, 10)]),
                uti=_attribute(index, [(1, 20), (2, 70), (9, 7)]),
                vacina_cov=_attribute(index, [(1, 30), (2, 60), (9, 7)]),
                vacina=_attribute(index, [(1, 40), (2, 50), (None, 7)]),
                hospital=1,
            )
        )
    for month_offset in range(12):
        year = 2025 + (8 + month_offset) // 12
        month = (8 + month_offset) % 12 + 1
        rows.append(_row(date(year, month, 15), "RJ", 1, 2, 2, 2, 1))
    frame = pd.DataFrame(rows)
    for column in schema.PROCESSED_COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    return frame.loc[:, list(schema.PROCESSED_COLUMNS)]


def _row(
    day: date,
    uf: str,
    evolucao: int | None,
    uti: int | None,
    vacina_cov: int | None,
    vacina: int | None,
    hospital: int | None,
) -> dict[str, object]:
    return {
        "dt_sin_pri": pd.Timestamp(day),
        "dt_notific": pd.Timestamp(day + timedelta(days=1)),
        "sem_pri": day.isocalendar().week,
        "sg_uf_not": uf,
        "sg_uf": uf,
        "cs_sexo": "F",
        "hospital": hospital,
        "uti": uti,
        "evolucao": evolucao,
        "vacina_cov": vacina_cov,
        "vacina": vacina,
        "classi_fin": 4,
        "age_years": 60.0,
        "age_band": "60-69",
        "notif_hash": f"{hash((day, uf, len(uf))) & 0xFFFFFFFF:08x}{id(day) & 0xFFFFFFFF:08x}",
        "source_file": "synthetic",
    }


def build_synthetic_database(root: Path) -> Path:
    """Write the synthetic Parquet and DuckDB file under `root`; returns the DuckDB path."""
    parquet = root / "processed" / "srag.parquet"
    parquet.parent.mkdir(parents=True, exist_ok=True)
    frame = synthetic_cases()
    for column in (*schema.EVENT_DATE_COLUMNS, *schema.VACCINE_DATE_COLUMNS):
        frame[column.lower()] = pd.to_datetime(frame[column.lower()])
    for column in schema.CODE_COLUMNS:
        frame[column.lower()] = frame[column.lower()].astype("Int16")
    frame.to_parquet(parquet, index=False)
    database = root / "srag.duckdb"
    build_database(parquet, database)
    return database
