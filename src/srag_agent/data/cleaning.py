"""Pure, vectorised cleaning functions for the raw Sivep-Gripe extract."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from srag_agent.data import schema

ISO_DATE_FORMAT = "%Y-%m-%d"
BR_DATE_FORMAT = "%d/%m/%Y"
HASH_LENGTH = 16
DAYS_PER_YEAR = 365.25
MONTHS_PER_YEAR = 12
MAX_PLAUSIBLE_AGE = 120


@dataclass
class CleaningStats:
    """Counts produced while cleaning one raw file."""

    source_file: str
    rows_in: int
    rows_out: int = 0
    invalid_dates: dict[str, int] = field(default_factory=dict)
    implausible_ages: int = 0


def parse_mixed_date(values: pd.Series) -> pd.Series:
    """Parse dates written either as ISO `yyyy-mm-ddT00:00:00.000Z` or as `dd/mm/yyyy`.

    Unparseable values become `NaT`. Both layouts occur in the same extract (ISO for
    episode dates, Brazilian for covid-19 vaccine doses).
    """
    text = values.astype("string").str.strip()
    iso = pd.to_datetime(text.str.slice(0, 10), format=ISO_DATE_FORMAT, errors="coerce")
    brazilian = pd.to_datetime(text, format=BR_DATE_FORMAT, errors="coerce")
    return iso.fillna(brazilian)


def nullify_outside(dates: pd.Series, start: date, end: date) -> pd.Series:
    """Replace dates outside `[start, end]` with `NaT` (typos such as year 8202)."""
    lower = pd.Timestamp(start)
    upper = pd.Timestamp(end)
    inside = (dates >= lower) & (dates <= upper)
    return dates.where(inside)


def to_code(values: pd.Series) -> pd.Series:
    """Convert DATASUS code strings to nullable small integers."""
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.round().astype("Int16")


def age_in_years(nu_idade: pd.Series, tp_idade: pd.Series) -> pd.Series:
    """Convert `NU_IDADE_N` + `TP_IDADE` (1=days, 2=months, 3=years) to years.

    Implausible ages (negative, above 120 or with unknown unit) become `NaN`.
    """
    value = pd.to_numeric(nu_idade, errors="coerce").astype("float64")
    unit = pd.to_numeric(tp_idade, errors="coerce")
    years = value.where(unit == 3)
    years = years.fillna(value.where(unit == 2) / MONTHS_PER_YEAR)
    years = years.fillna(value.where(unit == 1) / DAYS_PER_YEAR)
    plausible = (years >= 0) & (years <= MAX_PLAUSIBLE_AGE)
    return years.where(plausible)


def age_band(years: pd.Series) -> pd.Series:
    """Bucket ages into 10-year bands (`0-9` ... `80+`); unknown ages stay null."""
    bins = [*schema.AGE_BAND_EDGES, float("inf")]
    banded = pd.cut(years, bins=bins, labels=schema.AGE_BAND_LABELS, right=False)
    return banded.astype("string")


def hash_identifier(values: pd.Series) -> pd.Series:
    """Replace an identifier by a truncated SHA-256 digest, usable only for deduplication."""

    def digest(value: object) -> str | None:
        if value is None or pd.isna(value):
            return None
        return hashlib.sha256(str(value).strip().encode("utf-8")).hexdigest()[:HASH_LENGTH]

    return values.map(digest).astype("string")


def _filled(raw: pd.Series) -> pd.Series:
    """True where the raw text column had a non-blank value."""
    return raw.astype("string").str.strip().fillna("") != ""


def _count_invalid(raw: pd.Series, parsed: pd.Series) -> int:
    """Values that were present in the raw file but did not survive parsing/validation."""
    return int((_filled(raw) & parsed.isna()).sum())


def _clean_dates(
    raw: pd.DataFrame, columns: tuple[str, ...], start: date, end: date, stats: CleaningStats
) -> dict[str, pd.Series]:
    cleaned: dict[str, pd.Series] = {}
    for column in columns:
        parsed = nullify_outside(parse_mixed_date(raw[column]), start, end)
        stats.invalid_dates[column.lower()] = _count_invalid(raw[column], parsed)
        cleaned[column.lower()] = parsed
    return cleaned


def clean_cases(
    raw: pd.DataFrame, extraction_date: date, source_file: str
) -> tuple[pd.DataFrame, CleaningStats]:
    """Transform a raw frame (string columns from `schema.RAW_COLUMNS_TO_READ`) into the
    processed layout, dropping every column outside the contract.
    """
    stats = CleaningStats(source_file=source_file, rows_in=len(raw))
    out = pd.DataFrame(index=raw.index)

    event_start = date.fromisoformat(schema.EPIDEMIOLOGICAL_WINDOW_START)
    vaccine_start = date.fromisoformat(schema.VACCINE_WINDOW_START)
    dates = {
        **_clean_dates(raw, schema.EVENT_DATE_COLUMNS, event_start, extraction_date, stats),
        **_clean_dates(raw, schema.VACCINE_DATE_COLUMNS, vaccine_start, extraction_date, stats),
    }
    for column, parsed in dates.items():
        out[column] = parsed

    for column in schema.CODE_COLUMNS:
        out[column.lower()] = to_code(raw[column])

    for column in schema.TEXT_COLUMNS:
        out[column.lower()] = raw[column].astype("string").str.strip().str.upper()

    years = age_in_years(raw[schema.RAW_AGE_COLUMN], raw["TP_IDADE"])
    stats.implausible_ages = _count_invalid(raw[schema.RAW_AGE_COLUMN], years)
    out["age_years"] = years.round(2)
    out["age_band"] = age_band(years)
    out["notif_hash"] = hash_identifier(raw[schema.RAW_IDENTIFIER])
    out["source_file"] = pd.Series(source_file, index=raw.index, dtype="string")

    out = out.loc[:, list(schema.PROCESSED_COLUMNS)]
    stats.rows_out = len(out)
    return out, stats


def drop_duplicate_notifications(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Keep the first row per `notif_hash`; rows without a hash are kept as they are."""
    has_hash = frame["notif_hash"].notna()
    deduplicated = pd.concat(
        [frame[has_hash].drop_duplicates(subset="notif_hash", keep="first"), frame[~has_hash]]
    )
    removed = len(frame) - len(deduplicated)
    return deduplicated.reset_index(drop=True), removed
