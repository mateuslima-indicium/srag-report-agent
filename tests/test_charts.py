"""Charts render to PNG files of the expected size."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from srag_agent.data.db import open_readonly
from srag_agent.metrics.series import daily_cases, monthly_cases
from srag_agent.report.charts import HEIGHT_PX, WIDTH_PX, plot_daily_cases, plot_monthly_cases
from tests.synthetic import REFERENCE_DATE, build_synthetic_database


def test_charts_render_png_at_expected_size(tmp_path: Path) -> None:
    database = build_synthetic_database(tmp_path)
    with open_readonly(database) as con:
        daily = daily_cases(con, REFERENCE_DATE)
        monthly = monthly_cases(con, REFERENCE_DATE)
    daily_png = plot_daily_cases(daily, tmp_path / "out" / "daily.png")
    monthly_png = plot_monthly_cases(monthly, tmp_path / "out" / "monthly.png")
    for png in (daily_png, monthly_png):
        assert png.exists()
        with Image.open(png) as image:
            assert image.size == (WIDTH_PX, HEIGHT_PX)
