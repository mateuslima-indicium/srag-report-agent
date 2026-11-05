"""Structured report content produced by the LLM (text only; numbers come from tools)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MetricCommentary(BaseModel):
    metric_name: str = Field(
        description=(
            "Um de: case_growth_7d, case_growth_30d, mortality_rate, icu_rate, "
            "vaccination_covid, vaccination_flu"
        )
    )
    headline: str = Field(description="Uma frase com o valor e a leitura principal")
    interpretation: str = Field(
        description="Interpretação em 2 a 4 frases, citando os caveats da métrica"
    )


class NewsReference(BaseModel):
    news_id: str = Field(description="Id da notícia citada, ex. n2")
    relevance: str = Field(description="Por que a notícia ajuda a contextualizar os números")


class ReportContent(BaseModel):
    """Everything the writer node must fill in, in Brazilian Portuguese."""

    executive_summary: str = Field(description="Resumo executivo em um parágrafo")
    metric_sections: list[MetricCommentary] = Field(
        description="Exatamente uma entrada por métrica, na ordem acima"
    )
    deep_dive: str = Field(
        default="",
        description="Achados das consultas adicionais (por UF, faixa etária etc.), se houver",
    )
    news_context: str = Field(
        description="Como as notícias dialogam com os números; cite ids entre colchetes, ex. [n1]"
    )
    cited_news: list[NewsReference] = Field(default_factory=list)
    limitations: list[str] = Field(description="Limitações dos dados e das métricas")

    @property
    def cited_ids(self) -> set[str]:
        return {reference.news_id for reference in self.cited_news}
