"""Unit tests for the pure cleaning functions."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from srag_agent.data import cleaning


def test_parse_mixed_date_accepts_iso_and_brazilian_layouts() -> None:
    raw = pd.Series(
        ["2026-01-05T00:00:00.000Z", "05/01/2026", " 2026-02-01T00:00:00.000Z ", "x", None]
    )
    parsed = cleaning.parse_mixed_date(raw)
    assert parsed.iloc[0] == pd.Timestamp("2026-01-05")
    assert parsed.iloc[1] == pd.Timestamp("2026-01-05")
    assert parsed.iloc[2] == pd.Timestamp("2026-02-01")
    assert pd.isna(parsed.iloc[3])
    assert pd.isna(parsed.iloc[4])


def test_nullify_outside_drops_absurd_years() -> None:
    dates = pd.to_datetime(pd.Series(["8202-03-01", "2026-05-01", "2029-01-01", "2024-11-30"]))
    cleaned = cleaning.nullify_outside(dates, date(2024, 12, 1), date(2026, 11, 2))
    assert cleaned.isna().tolist() == [True, False, True, True]


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [("67", "3", 67.0), ("6", "2", 0.5), ("73", "1", 0.2), ("150", "3", None), ("5", "7", None)],
)
def test_age_in_years_handles_units_and_implausible_values(
    value: str, unit: str, expected: float | None
) -> None:
    years = cleaning.age_in_years(pd.Series([value]), pd.Series([unit]))
    if expected is None:
        assert pd.isna(years.iloc[0])
    else:
        assert years.iloc[0] == pytest.approx(expected, abs=0.01)


def test_age_band_uses_ten_year_buckets() -> None:
    bands = cleaning.age_band(pd.Series([0.2, 9.9, 10.0, 45.0, 80.0, 101.0, None]))
    assert bands.tolist()[:6] == ["0-9", "0-9", "10-19", "40-49", "80+", "80+"]
    assert pd.isna(bands.iloc[6])


def test_hash_identifier_is_deterministic_and_irreversible() -> None:
    hashed = cleaning.hash_identifier(pd.Series(["1001", " 1001 ", "1002", None]))
    assert hashed.iloc[0] == hashed.iloc[1]
    assert hashed.iloc[0] != hashed.iloc[2]
    assert len(hashed.iloc[0]) == cleaning.HASH_LENGTH
    assert "1001" not in hashed.iloc[0]
    assert pd.isna(hashed.iloc[3])


def test_to_code_coerces_invalid_values_to_null() -> None:
    codes = cleaning.to_code(pd.Series(["1", "2", "abc", "", None, "9.0"]))
    assert codes.tolist()[:2] == [1, 2]
    assert codes.isna().tolist()[2:5] == [True, True, True]
    assert codes.iloc[5] == 9
    assert str(codes.dtype) == "Int16"


def test_drop_duplicate_notifications_keeps_rows_without_hash() -> None:
    frame = pd.DataFrame({"notif_hash": ["a", "a", None, None, "b"], "v": [1, 2, 3, 4, 5]})
    deduplicated, removed = cleaning.drop_duplicate_notifications(frame)
    assert removed == 1
    assert sorted(deduplicated["v"].tolist()) == [1, 3, 4, 5]
