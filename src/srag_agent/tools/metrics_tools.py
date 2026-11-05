"""One LangChain tool per deterministic metric and series."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date
from typing import Literal

import duckdb
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from srag_agent.audit import AuditLogger
from srag_agent.data.schema import BRAZIL_UFS
from srag_agent.metrics.base import resolve_reference_date, validate_uf
from srag_agent.metrics.cases import case_growth
from srag_agent.metrics.icu import icu_rate
from srag_agent.metrics.models import MetricResult, SeriesResult
from srag_agent.metrics.mortality import mortality_rate
from srag_agent.metrics.series import daily_cases, monthly_cases
from srag_agent.metrics.vaccination import covid_vaccination_rate, flu_vaccination_rate

Uf = Literal[BRAZIL_UFS]  # type: ignore[valid-type]


class MetricInput(BaseModel):
    reference_date: date | None = Field(
        default=None, description="Data de referência (YYYY-MM-DD). Padrão: último caso do banco."
    )
    uf: Uf | None = Field(default=None, description="Sigla da UF para recortar; vazio = Brasil.")


class GrowthInput(MetricInput):
    window_days: Literal[7, 30] = Field(default=30, description="Janela de comparação em dias.")


class RateInput(MetricInput):
    window_days: Literal[7, 30, 60, 90] = Field(default=30, description="Janela em dias.")


MetricFn = Callable[..., MetricResult | SeriesResult | list[MetricResult]]


def build_metric_tools(con: duckdb.DuckDBPyConnection, audit: AuditLogger) -> list[StructuredTool]:
    """Tools share the read-only connection and log every call to the audit trail."""

    def wrap(
        name: str, description: str, schema: type[BaseModel], compute: MetricFn
    ) -> StructuredTool:
        def run(**kwargs: object) -> str:
            started = time.perf_counter()
            try:
                reference = resolve_reference_date(con, kwargs.pop("reference_date", None))
                uf = validate_uf(kwargs.pop("uf", None))
                result = compute(con, reference, uf=uf, **kwargs)
            except ValueError as error:
                audit.log("tool_call", name, args=_safe(kwargs), error=str(error))
                return f"ERRO: {error}"
            payload = (
                "[" + ",".join(r.model_dump_json() for r in result) + "]"
                if isinstance(result, list)
                else result.model_dump_json()
            )
            audit.log(
                "tool_call",
                name,
                args={"reference_date": reference.isoformat(), "uf": uf, **_safe(kwargs)},
                result_chars=len(payload),
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
            return payload

        return StructuredTool.from_function(
            func=run, name=name, description=description, args_schema=schema
        )

    return [
        wrap(
            "get_case_growth",
            "Taxa de aumento de casos de SRAG: casos nos últimos N dias sobre os N dias "
            "anteriores, menos 1. Inclui o valor sobre dados consolidados e os caveats.",
            GrowthInput,
            lambda con, ref, uf, window_days=30: case_growth(con, ref, window_days, uf),
        ),
        wrap(
            "get_mortality_rate",
            "Taxa de mortalidade entre casos de SRAG com desfecho conhecido na janela.",
            RateInput,
            lambda con, ref, uf, window_days=30: mortality_rate(con, ref, window_days, uf),
        ),
        wrap(
            "get_icu_rate",
            "Proporção de internados por SRAG que foram para UTI na janela (proxy de UTI).",
            RateInput,
            lambda con, ref, uf, window_days=30: icu_rate(con, ref, window_days, uf),
        ),
        wrap(
            "get_vaccination_rates",
            "Proporção de casos de SRAG vacinados (covid-19 e gripe) na janela; proxy, não "
            "cobertura populacional.",
            RateInput,
            lambda con, ref, uf, window_days=30: [
                covid_vaccination_rate(con, ref, window_days, uf),
                flu_vaccination_rate(con, ref, window_days, uf),
            ],
        ),
        wrap(
            "get_daily_cases_series",
            "Casos diários de SRAG nos 30 dias até a data de referência, com flag preliminar.",
            MetricInput,
            lambda con, ref, uf: daily_cases(con, ref, uf),
        ),
        wrap(
            "get_monthly_cases_series",
            "Casos mensais de SRAG nos 12 meses completos antes da data de referência.",
            MetricInput,
            lambda con, ref, uf: monthly_cases(con, ref, uf),
        ),
    ]


def _safe(kwargs: dict[str, object]) -> dict[str, object]:
    return {
        key: (value.isoformat() if isinstance(value, date) else value)
        for key, value in kwargs.items()
    }
