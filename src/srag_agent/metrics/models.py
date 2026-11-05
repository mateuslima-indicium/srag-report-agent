"""Pydantic models shared by every deterministic metric and series."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

MetricUnit = Literal["percent_change", "share"]


def pt_percent(value: float | None, signed: bool = False) -> str:
    """`0.117 -> '11,7%'`, `-0.032 -> '-3,2%'` (Brazilian decimal comma); None -> 'n/d'."""
    if value is None:
        return "n/d"
    text = f"{value * 100:+.1f}%" if signed else f"{value * 100:.1f}%"
    return text.replace(".", ",")


class MetricResult(BaseModel):
    """One computed metric with everything needed to audit and re-check it."""

    name: str = Field(description="Stable identifier, e.g. `case_growth_7d`")
    label: str = Field(description="Human label in Portuguese")
    value: float | None = Field(description="Ratio; None when the denominator is zero")
    unit: MetricUnit
    numerator: int
    denominator: int
    window_start: date
    window_end: date
    reference_date: date
    uf: str | None = None
    definition: str = Field(description="How the value was computed, in Portuguese")
    caveats: list[str] = Field(default_factory=list)
    extra: dict[str, float | int] = Field(default_factory=dict)

    @property
    def as_percent(self) -> float | None:
        return None if self.value is None else self.value * 100

    @property
    def formatted(self) -> str:
        """Value as shown in the report, e.g. `+61,7%` for changes and `11,8%` for shares."""
        return pt_percent(self.value, signed=self.unit == "percent_change")


class SeriesPoint(BaseModel):
    period: date
    cases: int
    preliminary: bool = False


class SeriesResult(BaseModel):
    """A time series of case counts (daily or monthly)."""

    name: str
    label: str
    granularity: Literal["daily", "monthly"]
    reference_date: date
    uf: str | None = None
    points: list[SeriesPoint]
    preliminary_cutoff: date = Field(
        description="Periods after this date are flagged as preliminary (reporting lag)"
    )
    definition: str
    caveats: list[str] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(point.cases for point in self.points)


class MetricsBundle(BaseModel):
    """Everything the deterministic layer hands to the agent and the renderer."""

    reference_date: date
    latest_case_date: date
    uf: str | None
    metrics: list[MetricResult]
    series: list[SeriesResult]

    def metric(self, name: str) -> MetricResult:
        for item in self.metrics:
            if item.name == name:
                return item
        msg = f"Unknown metric {name!r}"
        raise KeyError(msg)

    def get_series(self, name: str) -> SeriesResult:
        for item in self.series:
            if item.name == name:
                return item
        msg = f"Unknown series {name!r}"
        raise KeyError(msg)
