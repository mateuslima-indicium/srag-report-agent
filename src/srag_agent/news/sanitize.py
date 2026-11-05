"""Turn raw feed text into short, plain, bounded strings."""

from __future__ import annotations

import html
import re

MAX_CHARS = 600
_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


def strip_html(text: str) -> str:
    """Remove tags and decode entities; collapses whitespace."""
    without_tags = _TAG.sub(" ", text or "")
    return _WHITESPACE.sub(" ", html.unescape(without_tags)).strip()


def truncate(text: str, limit: int = MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def clean_text(text: str, limit: int = MAX_CHARS) -> str:
    return truncate(strip_html(text), limit)


def strip_source_suffix(title: str, source: str) -> str:
    """Google News appends ` - Source` to titles; drop it when it matches the source."""
    suffix = f" - {source}"
    if source and title.endswith(suffix):
        return title[: -len(suffix)].rstrip()
    return title
