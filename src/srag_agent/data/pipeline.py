"""Build the de-identified processed dataset from the raw Open DATASUS CSVs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from srag_agent.data import schema
from srag_agent.data.cleaning import CleaningStats, clean_cases, drop_duplicate_notifications
from srag_agent.data.db import build_database

_EXTRACTION_DATE_PATTERN = re.compile(r"(\d{2})-(\d{2})-(\d{4})\.csv$", re.IGNORECASE)
_ENCODINGS = ("utf-8", "latin-1")
KEY_COLUMNS_FOR_QUALITY = (
    "dt_sin_pri",
    "dt_notific",
    "hospital",
    "uti",
    "evolucao",
    "dt_evoluca",
    "classi_fin",
    "vacina",
    "vacina_cov",
    "age_years",
    "sg_uf_not",
)


@dataclass
class DatasetQualityReport:
    """Everything `docs/data-quality.md` needs to describe one build."""

    extraction_date: date
    built_at: date
    per_file: list[CleaningStats] = field(default_factory=list)
    duplicates_removed: int = 0
    rows_total: int = 0
    null_share: dict[str, float] = field(default_factory=dict)
    date_ranges: dict[str, tuple[date | None, date | None]] = field(default_factory=dict)
    parquet_bytes: int = 0


def extraction_date_from_filename(path: Path) -> date | None:
    """`INFLUD26-02-11-2026.csv` -> 2026-11-02 (dd-mm-yyyy suffix used by DATASUS)."""
    match = _EXTRACTION_DATE_PATTERN.search(path.name)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    return date(year, month, day)


def read_raw_csv(path: Path, encoding: str | None = None) -> pd.DataFrame:
    """Load only `schema.RAW_COLUMNS_TO_READ` from a DATASUS CSV, every column as text.

    DuckDB does the parsing (fast, streaming). Files are UTF-8 as of the 2026 extract;
    older extracts were latin-1, so both are tried.
    """
    encodings = (encoding,) if encoding else _ENCODINGS
    columns = ", ".join(f'"{column}"' for column in schema.RAW_COLUMNS_TO_READ)
    last_error: Exception | None = None
    for candidate in encodings:
        sql = (
            f"SELECT {columns} FROM read_csv(?, delim=';', header=true, quote='\"', "
            f"all_varchar=true, encoding=?)"
        )
        try:
            with duckdb.connect() as con:
                return con.execute(sql, [path.as_posix(), candidate]).df()
        except duckdb.InvalidInputException as error:
            last_error = error
    msg = f"Could not read {path} with encodings {encodings}"
    raise ValueError(msg) from last_error


def build_processed_frame(
    raw_paths: list[Path], extraction_date: date
) -> tuple[pd.DataFrame, DatasetQualityReport]:
    """Clean and concatenate every raw file, then deduplicate by notification hash."""
    report = DatasetQualityReport(extraction_date=extraction_date, built_at=date.today())
    frames: list[pd.DataFrame] = []
    for path in raw_paths:
        cleaned, stats = clean_cases(read_raw_csv(path), extraction_date, path.name)
        report.per_file.append(stats)
        frames.append(cleaned)
    combined = pd.concat(frames, ignore_index=True)
    deduplicated, report.duplicates_removed = drop_duplicate_notifications(combined)
    report.rows_total = len(deduplicated)
    report.null_share = {
        column: round(float(deduplicated[column].isna().mean()), 4)
        for column in KEY_COLUMNS_FOR_QUALITY
    }
    for column in (*schema.EVENT_DATE_COLUMNS, *schema.VACCINE_DATE_COLUMNS):
        series = deduplicated[column.lower()]
        lower = series.min()
        upper = series.max()
        report.date_ranges[column.lower()] = (
            None if pd.isna(lower) else lower.date(),
            None if pd.isna(upper) else upper.date(),
        )
    return deduplicated, report


def write_parquet(frame: pd.DataFrame, parquet_path: Path) -> int:
    """Persist the processed frame with zstd compression; returns the file size in bytes."""
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet_path, engine="pyarrow", compression="zstd", index=False)
    return parquet_path.stat().st_size


def build_dataset(
    raw_paths: list[Path],
    parquet_path: Path,
    db_path: Path,
    extraction_date: date | None = None,
) -> DatasetQualityReport:
    """Full pipeline: raw CSVs -> processed Parquet -> DuckDB file."""
    if not raw_paths:
        msg = "No raw CSV files to process"
        raise ValueError(msg)
    resolved_date = extraction_date or max(
        (d for d in map(extraction_date_from_filename, raw_paths) if d), default=date.today()
    )
    frame, report = build_processed_frame(raw_paths, resolved_date)
    report.parquet_bytes = write_parquet(frame, parquet_path)
    build_database(parquet_path, db_path)
    return report


def render_quality_report(report: DatasetQualityReport) -> str:
    """Markdown (pt-BR) summary of the build for `docs/data-quality.md`."""
    lines = [
        "# Qualidade do dataset processado",
        "",
        f"Gerado em {report.built_at.isoformat()} por `scripts/build_dataset.py`. "
        f"Extração do DATASUS: {report.extraction_date.isoformat()}.",
        "",
        "## Linhas por arquivo",
        "",
        "| Arquivo | Linhas lidas | Linhas mantidas | Idades implausíveis |",
        "|---|---:|---:|---:|",
    ]
    for stats in report.per_file:
        lines.append(
            f"| `{stats.source_file}` | {stats.rows_in:,} | {stats.rows_out:,} "
            f"| {stats.implausible_ages:,} |"
        )
    lines += [
        "",
        f"Duplicatas removidas (mesmo hash de notificação): {report.duplicates_removed:,}.",
        f"Total final: **{report.rows_total:,} linhas**, "
        f"{report.parquet_bytes / 1_048_576:.1f} MB em Parquet (zstd).",
        "",
        "## Datas inválidas ou fora da janela plausível",
        "",
        "Valores preenchidos que viraram nulo por não serem datas ou por cair fora de "
        f"[{schema.EPIDEMIOLOGICAL_WINDOW_START}, extração] (episódio) ou "
        f"[{schema.VACCINE_WINDOW_START}, extração] (vacinas).",
        "",
        "| Coluna | " + " | ".join(f"`{s.source_file}`" for s in report.per_file) + " |",
        "|---|" + "---:|" * len(report.per_file),
    ]
    columns = report.per_file[0].invalid_dates if report.per_file else {}
    for column in columns:
        counts = " | ".join(f"{s.invalid_dates.get(column, 0):,}" for s in report.per_file)
        lines.append(f"| `{column}` | {counts} |")
    lines += [
        "",
        "## Nulos nas colunas-chave (após limpeza)",
        "",
        "| Coluna | % nulos |",
        "|---|---:|",
    ]
    for column, share in report.null_share.items():
        lines.append(f"| `{column}` | {share * 100:.1f}% |")
    lines += ["", "## Faixa de datas", "", "| Coluna | Mínimo | Máximo |", "|---|---|---|"]
    for column, (lower, upper) in report.date_ranges.items():
        lines.append(f"| `{column}` | {lower or '-'} | {upper or '-'} |")
    lines += [
        "",
        "## Colunas removidas por privacidade",
        "",
        "Nenhuma das colunas abaixo existe no Parquet nem é lida pelo pipeline além do "
        "necessário para derivar o hash de deduplicação:",
        "",
        ", ".join(f"`{c}`" for c in sorted(schema.PRIVACY_DROPPED_COLUMNS)),
        "",
    ]
    return "\n".join(lines)
