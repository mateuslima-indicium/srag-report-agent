"""Block personally identifiable information from ever reaching the rendered report."""

from __future__ import annotations

import re

PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cpf", re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{3}\d{3}\d{3}\d{2}\b(?=\D|$)")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("phone", re.compile(r"(?:\(\d{2}\)\s?|\b\d{2}\s)9?\d{4}-\d{4}\b")),
    ("cns", re.compile(r"\b[1-2789]\d{14}\b")),
    ("notification_number", re.compile(r"\b\d{12,14}\b")),
)


def find_pii(text: str) -> list[str]:
    """Return the labels of every PII pattern matched (empty when clean)."""
    return [label for label, pattern in PII_PATTERNS if pattern.search(text)]
