"""Every number the LLM writes must trace back to a tool result or a metric.

The check extracts percentages and integers from the generated text and looks each one up in
the set of values produced deterministically during the run (metrics, series, tool outputs,
news titles). Numbers with no origin are reported so the writer can be asked to fix them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from srag_agent.metrics.base import GROWTH_WINDOWS, PRELIMINARY_DAYS, RATE_WINDOWS
from srag_agent.metrics.models import MetricsBundle
from srag_agent.news.models import NewsBatch
from srag_agent.report.models import ReportContent

PERCENT_TOLERANCE = 0.1
INTEGER_TOLERANCE = 1
IGNORED_BELOW = 13
"""Small integers (window sizes, list counts, 'duas UFs') are never flagged."""

_DATE_LIKE = re.compile(
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{4}\b|\b\d{1,2}/\d{1,2}\b"
    r"|\b(?:19|20)\d{2}\b|\b\d{1,2}h\d{0,2}\b|\bn\d+\b|\b\d{1,2}-\d{1,2}\b|\b\d{2}\+"
)
_PERCENT = re.compile(r"([+-]?\d+(?:[.,]\d+)?)\s*%")
_INTEGER = re.compile(
    r"(?<![\d.,])[+-]?\d{1,3}(?:\.\d{3})+(?![\d,])|(?<![\d.,])[+-]?\d+(?![\d.,%])"
)
_JSON_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass
class NumericCheck:
    passed: bool
    checked: int
    unverified: list[str] = field(default_factory=list)

    @property
    def issue(self) -> str:
        sample = ", ".join(self.unverified[:12])
        more = "" if len(self.unverified) <= 12 else f" (+{len(self.unverified) - 12})"
        return (
            f"Números sem origem nas ferramentas: {sample}{more}. Use apenas valores que "
            "apareçam literalmente nos resultados das ferramentas; não faça cálculos próprios."
        )


def _to_float(token: str) -> float:
    return float(token.replace(".", "").replace(",", ".")) if "," in token else float(token)


def _to_int(token: str) -> int:
    return int(token.replace(".", "").replace("+", ""))


def draft_text(draft: ReportContent) -> str:
    parts = [
        draft.executive_summary,
        draft.deep_dive,
        draft.news_context,
        *(f"{s.headline} {s.interpretation}" for s in draft.metric_sections),
        *draft.limitations,
        *(r.relevance for r in draft.cited_news),
    ]
    return "\n".join(parts)


def extract_numbers(text: str) -> tuple[list[float], list[int]]:
    """Percentages and integers written in the text (dates, years and ids removed first)."""
    cleaned = _DATE_LIKE.sub(" ", text)
    percents = [_to_float(match) for match in _PERCENT.findall(cleaned)]
    without_percents = _PERCENT.sub(" ", cleaned)
    integers = []
    for match in _INTEGER.findall(without_percents):
        value = _to_int(match)
        if abs(value) >= IGNORED_BELOW:
            integers.append(value)
    return percents, integers


def _add_ratio(percents: set[float], value: float) -> None:
    if -1.0 <= value <= 1.0:
        percents.add(round(value * 100, 1))
    percents.add(round(value, 1))


def allowed_values(
    bundle: MetricsBundle, news: NewsBatch, tool_outputs: list[str]
) -> tuple[set[int], set[float]]:
    """All numbers the writer may legitimately quote."""
    integers: set[int] = {PRELIMINARY_DAYS, *GROWTH_WINDOWS, *RATE_WINDOWS}
    percents: set[float] = {0.0}
    for metric in bundle.metrics:
        window_days = (metric.window_end - metric.window_start).days + 1
        integers.update({metric.numerator, metric.denominator, window_days})
        if metric.value is not None:
            _add_ratio(percents, metric.value)
        for extra in metric.extra.values():
            if isinstance(extra, bool):
                continue
            if isinstance(extra, int):
                integers.add(extra)
            else:
                _add_ratio(percents, float(extra))
                if float(extra).is_integer():
                    integers.add(int(extra))
        _absorb_text(
            " ".join([metric.label, metric.definition, *metric.caveats]), integers, percents
        )
    for series in bundle.series:
        integers.update({series.total, len(series.points)})
        integers.update(point.cases for point in series.points)
    for item in news.items:
        _absorb_text(f"{item.title} {item.summary}", integers, percents)
    for output in tool_outputs:
        _absorb_tool_output(output, integers, percents)
    return integers, percents


def _absorb_text(text: str, integers: set[int], percents: set[float]) -> None:
    found_percents, found_integers = extract_numbers(text)
    percents.update(round(p, 1) for p in found_percents)
    integers.update(found_integers)


def _absorb_tool_output(output: str, integers: set[int], percents: set[float]) -> None:
    try:
        payload = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        _absorb_text(output, integers, percents)
        return
    for token in _JSON_NUMBER.findall(json.dumps(payload)):
        value = float(token)
        if value.is_integer():
            integers.add(int(value))
        else:
            _add_ratio(percents, value)


def _close_percent(value: float, allowed: set[float]) -> bool:
    """Sign-insensitive: "queda de 3,2%" is the same number as the metric's "-3,2%"."""
    magnitude = abs(value)
    return any(abs(magnitude - abs(candidate)) <= PERCENT_TOLERANCE + 1e-9 for candidate in allowed)


def _close_integer(value: int, allowed: set[int]) -> bool:
    return any(abs(value - candidate) <= INTEGER_TOLERANCE for candidate in allowed)


def check_numbers(
    draft: ReportContent, bundle: MetricsBundle, news: NewsBatch, tool_outputs: list[str]
) -> NumericCheck:
    integers, percents = allowed_values(bundle, news, tool_outputs)
    found_percents, found_integers = extract_numbers(draft_text(draft))
    unverified: list[str] = []
    for value in found_percents:
        if not _close_percent(value, percents) and not (
            value.is_integer() and _close_integer(int(value), integers)
        ):
            unverified.append(f"{value:g}%".replace(".", ","))
    for value in found_integers:
        if not _close_integer(value, integers):
            unverified.append(str(value))
    unique = list(dict.fromkeys(unverified))
    return NumericCheck(
        passed=not unique,
        checked=len(found_percents) + len(found_integers),
        unverified=unique,
    )
