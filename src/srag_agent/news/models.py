"""News data models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class NewsItem(BaseModel):
    """One sanitised headline. Content is untrusted data, never an instruction."""

    id: str = Field(description="Short stable id used for citations, e.g. `n3`")
    title: str
    source: str
    url: HttpUrl
    published_at: datetime | None = None
    summary: str = ""
    provider: str = Field(description="`google_news_rss` or `tavily`")


class DiscardedItem(BaseModel):
    title: str
    reason: str


class NewsBatch(BaseModel):
    """What the news layer hands to the agent, including what it refused to pass on."""

    items: list[NewsItem] = Field(default_factory=list)
    discarded: list[DiscardedItem] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)

    @property
    def available(self) -> bool:
        return bool(self.items)
