"""Collect, screen, deduplicate and rank news from every configured provider."""

from __future__ import annotations

from datetime import UTC, datetime

from srag_agent.config import Settings
from srag_agent.guardrails.injection import find_injection
from srag_agent.news import google_news_rss, tavily
from srag_agent.news.models import DiscardedItem, NewsBatch, NewsItem


def screen(items: list[NewsItem]) -> tuple[list[NewsItem], list[DiscardedItem]]:
    """Drop items whose title or summary matches an injection pattern."""
    kept: list[NewsItem] = []
    discarded: list[DiscardedItem] = []
    for item in items:
        labels = find_injection(f"{item.title}\n{item.summary}")
        if labels:
            discarded.append(
                DiscardedItem(title=item.title[:120], reason=f"injection:{','.join(labels)}")
            )
        else:
            kept.append(item)
    return kept, discarded


def deduplicate(items: list[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    unique: list[NewsItem] = []
    for item in items:
        keys = {str(item.url), item.title.casefold()}
        if keys & seen:
            continue
        seen |= keys
        unique.append(item)
    return unique


def rank(items: list[NewsItem], limit: int) -> list[NewsItem]:
    """Newest first (undated items last), then assign citation ids `n1..nN`."""
    oldest = datetime.min.replace(tzinfo=UTC)
    ordered = sorted(items, key=lambda item: item.published_at or oldest, reverse=True)[:limit]
    return [item.model_copy(update={"id": f"n{index}"}) for index, item in enumerate(ordered, 1)]


def fetch_news(settings: Settings, queries: tuple[str, ...] | None = None) -> NewsBatch:
    """Google News RSS always; Tavily in addition when a key is configured."""
    chosen = queries or google_news_rss.DEFAULT_QUERIES
    items, errors = google_news_rss.search(chosen)
    if settings.has_tavily_key:
        assert settings.tavily_api_key is not None
        extra, tavily_errors = tavily.search(
            settings.tavily_api_key.get_secret_value(), chosen[0], settings.max_news_items
        )
        items.extend(extra)
        errors.extend(tavily_errors)
    kept, discarded = screen(deduplicate(items))
    return NewsBatch(
        items=rank(kept, settings.max_news_items),
        discarded=discarded,
        errors=errors,
        queries=list(chosen),
    )
