"""Optional Tavily news search, used only when `TAVILY_API_KEY` is set."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from srag_agent.news.models import NewsItem
from srag_agent.news.sanitize import clean_text

PROVIDER = "tavily"
ENDPOINT = "https://api.tavily.com/search"


def parse_response(payload: dict[str, Any]) -> list[NewsItem]:
    items: list[NewsItem] = []
    for result in payload.get("results", []):
        url = result.get("url")
        title = clean_text(str(result.get("title", "")), 300)
        if not url or not title:
            continue
        published = result.get("published_date")
        items.append(
            NewsItem(
                id="",
                title=title,
                source=clean_text(str(result.get("source") or url.split("/")[2]), 80),
                url=url,
                published_at=_parse_date(published),
                summary=clean_text(str(result.get("content", ""))),
                provider=PROVIDER,
            )
        )
    return items


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def search(
    api_key: str, query: str, max_results: int, timeout_seconds: float = 20.0
) -> tuple[list[NewsItem], list[str]]:
    body = {
        "query": query,
        "topic": "news",
        "days": 14,
        "max_results": max_results,
        "search_depth": "basic",
        "include_answer": False,
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        response = httpx.post(ENDPOINT, json=body, headers=headers, timeout=timeout_seconds)
        response.raise_for_status()
        return parse_response(response.json()), []
    except (httpx.HTTPError, ValueError) as error:
        return [], [f"{PROVIDER}: {type(error).__name__}: {error}"]
