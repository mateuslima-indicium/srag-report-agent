"""Live news: Google News RSS (no key) and optional Tavily, screened for prompt injection."""

from srag_agent.news.fetch import fetch_news
from srag_agent.news.models import DiscardedItem, NewsBatch, NewsItem

__all__ = ["DiscardedItem", "NewsBatch", "NewsItem", "fetch_news"]
