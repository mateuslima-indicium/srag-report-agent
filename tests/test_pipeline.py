"""End-to-end tests of the dataset build on a synthetic CSV."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from srag_agent.data import db, schema
from srag_agent.data.pipeline import (
    build_dataset,
    extraction_date_from_filename,
    render_quality_report,
)
from tests.conftest import FIXTURES_DIR

SAMPLE_CSV = FIXTURES_DIR / "srag_sample_02-11-2026.csv"


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, object]:
    root = tmp_path_factory.mktemp("dataset")
    parquet = root / "processed" / "srag.parquet"
    database = root / "srag.duckdb"
    report = build_dataset([SAMPLE_CSV], parquet, database)
    return parquet, database, report


def test_extraction_date_is_derived_from_filename() -> None:
    assert extraction_date_from_filename(SAMPLE_CSV) == date(2026, 11, 2)
    assert extraction_date_from_filename(Path("whatever.csv")) is None


def test_parquet_has_exact_contract_and_no_privacy_columns(built) -> None:
    parquet, _, _ = built
    frame = pd.read_parquet(parquet)
    assert list(frame.columns) == list(schema.PROCESSED_COLUMNS)
    leaked = {c for c in frame.columns if c.upper() in schema.PRIVACY_DROPPED_COLUMNS}
    assert not leaked
    assert "nu_notific" not in frame.columns
    assert "nu_idade_n" not in frame.columns


def test_duplicates_and_invalid_values_are_handled(built) -> None:
    parquet, _, report = built
    frame = pd.read_parquet(parquet)
    assert report.duplicates_removed == 1
    assert len(frame) == 7
    assert report.per_file[0].invalid_dates["dt_interna"] == 1  # year 8202
    assert report.per_file[0].invalid_dates["dt_entuti"] == 1  # year 2029
    assert frame["dt_interna"].isna().sum() == 2  # the absurd one plus a genuinely empty one
    assert frame["evolucao"].isna().sum() == 3  # 'abc' and two empties
    brazilian_layout = frame.loc[frame["sg_uf_not"] == "RS", "dt_sin_pri"].iloc[0]
    assert brazilian_layout == pd.Timestamp("2026-09-15")


def test_age_and_hash_derivations(built) -> None:
    parquet, _, _ = built
    frame = pd.read_parquet(parquet).set_index("sg_uf_not")
    assert frame.loc["SP", "age_years"].tolist() == [67.0, 46.0]
    assert frame.loc["MG", "age_years"] == pytest.approx(0.25)
    assert frame.loc["MG", "age_band"] == "0-9"
    assert pd.isna(frame.loc["PR", "age_years"])
    assert pd.isna(frame.loc["BA", "notif_hash"])
    assert frame["notif_hash"].dropna().str.len().eq(16).all()


def test_database_exposes_table_and_views(built) -> None:
    _, database, _ = built
    with db.open_readonly(database) as con:
        relations = {
            row["name"]
            for row in db.fetch_all(con, "SELECT table_name AS name FROM information_schema.tables")
        }
        assert set(db.QUERYABLE_RELATIONS) <= relations
        total = db.fetch_one(con, "SELECT count(*) AS n FROM cases")["n"]
        assert total == 7
        daily = db.fetch_all(con, "SELECT * FROM daily_cases ORDER BY case_date")
        assert daily[0]["case_date"] == date(2026, 9, 10)
        by_uf = {row["uf"]: row for row in db.fetch_all(con, "SELECT * FROM cases_by_uf")}
        assert by_uf["SP"]["cases"] == 2
        assert by_uf["RJ"]["deaths"] == 1
        assert by_uf["SP"]["icu_admissions"] == 1


def test_readonly_connection_rejects_writes(built) -> None:
    _, database, _ = built
    with db.open_readonly(database) as con, pytest.raises(Exception, match="read-only"):
        con.execute("DELETE FROM cases")


def test_ensure_database_rebuilds_when_missing(built, tmp_path: Path) -> None:
    parquet, _, _ = built
    fresh = tmp_path / "fresh.duckdb"
    assert db.ensure_database(parquet, fresh) == fresh
    assert fresh.exists()
    with pytest.raises(FileNotFoundError, match="build_dataset"):
        db.ensure_database(tmp_path / "missing.parquet", fresh)


def test_quality_report_mentions_key_facts(built) -> None:
    _, _, report = built
    text = render_quality_report(report)
    assert "srag_sample_02-11-2026.csv" in text
    assert "Duplicatas removidas (mesmo hash de notificação): 1." in text
    assert "`dt_interna` | 1" in text
    assert "`DT_NASC`" in text
