"""Build data/processed/srag.parquet, data/srag.duckdb and docs/data-quality.md."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from srag_agent.config import get_settings
from srag_agent.data.pipeline import build_dataset, render_quality_report

PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUALITY_DOC = PROJECT_ROOT / "docs" / "data-quality.md"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-dir", type=Path, default=None, help="folder with INFLUD*.csv (default: data/raw)"
    )
    args = parser.parse_args()
    settings = get_settings()
    raw_dir = args.raw_dir or settings.raw_dir
    raw_paths = sorted(raw_dir.glob("INFLUD*.csv"))
    if not raw_paths:
        print(f"no INFLUD*.csv in {raw_dir}; run scripts/download_data.py first", file=sys.stderr)
        sys.exit(1)
    print(f"building from {len(raw_paths)} file(s): {', '.join(p.name for p in raw_paths)}")
    report = build_dataset(raw_paths, settings.parquet_path, settings.db_path)
    QUALITY_DOC.write_text(render_quality_report(report), encoding="utf-8")
    print(
        f"rows={report.rows_total:,} duplicates_removed={report.duplicates_removed:,} "
        f"parquet={report.parquet_bytes / 1_048_576:.1f}MB -> {settings.parquet_path}"
    )
    print(f"database -> {settings.db_path}")
    print(f"quality report -> {QUALITY_DOC}")


if __name__ == "__main__":
    main()
