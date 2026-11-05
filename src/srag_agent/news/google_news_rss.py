"""Google News RSS search (no API key)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote_plus

import feedparser
import httpx

from srag_agent.news.models import NewsItem
from srag_agent.news.sanitize import clean_text, strip_source_suffix

PROVIDER = "google_news_rss"
BASE_URL = "https://news.google.com/rss/search"
USER_AGENT = "srag-report-agent/0.1 (+https://github.com/mateuslima-indicium/srag-report-agent)"
DEFAULT_QUERIES = (
    "SRAG síndrome respiratória aguda grave",
    "síndrome respiratória aguda grave internações",
    "vírus respiratório hospitalizações Brasil",
)


def feed_url(query: str) -> str:
    return f"{BASE_URL}?q={quote_plus(query)}&hl=pt-BR&gl=BR&ceid=BR:pt-150"


def fetch_feed(query: str, client: httpx.Client) -> bytes:
    response = client.get(feed_url(query), headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response.content


def _published(entry: dict[str, Any]) -> datetime | None:
    parsed = entry.get("published_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=UTC)


def parse_feed(content: bytes) -> list[NewsItem]:
    """Map RSS entries to `NewsItem`s (ids are assigned later, after deduplication)."""
    feed = feedparser.parse(content)
    items: list[NewsItem] = []
    for entry in feed.entries:
        link = entry.get("link")
        if not link:
            continue
        source = clean_text(str(entry.get("source", {}).get("title", "")), 80)
        title = strip_source_suffix(clean_text(str(entry.get("title", "")), 300), source)
        if not title:
            continue
        items.append(
            NewsItem(
                id="",
                title=title,
                source=source or "fonte não informada",
                url=link,
                published_at=_published(entry),
                summary=_summary(entry, title),
                provider=PROVIDER,
            )
        )
    return items


def _summary(entry: dict[str, Any], title: str) -> str:
    """Google's description is usually the title as a link; keep only genuine extra text."""
    text = clean_text(str(entry.get("summary", "")))
    for noise in (title, entry.get("source", {}).get("title", "")):
        text = text.replace(noise, "").strip()
    return "" if len(text) < 20 else text


def search(
    queries: tuple[str, ...], timeout_seconds: float = 20.0
) -> tuple[list[NewsItem], list[str]]:
    """Run every query and return the raw items plus any per-query error messages."""
    items: list[NewsItem] = []
    errors: list[str] = []
    with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
        for query in queries:
            try:
                items.extend(parse_feed(fetch_feed(query, client)))
            except (httpx.HTTPError, ValueError) as error:
                errors.append(f"{PROVIDER} '{query}': {type(error).__name__}: {error}")
    return items, errors
