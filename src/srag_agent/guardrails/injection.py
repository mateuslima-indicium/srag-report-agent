"""Prompt-injection screening for untrusted text (news items) before it reaches the LLM."""

from __future__ import annotations

import re
import unicodedata

INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(pattern, re.IGNORECASE))
    for label, pattern in (
        (
            "ignore_instructions_pt",
            r"\b(ignore|desconsidere|esque[cç]a)\b.{0,40}\b(instru[cç][oõ]es|regras|prompt)",
        ),
        (
            "ignore_instructions_en",
            r"\b(ignore|disregard|forget)\b.{0,40}\b(instructions|rules|prompt)",
        ),
        ("system_prompt", r"\bsystem\s*prompt\b|\bprompt\s+do\s+sistema\b"),
        (
            "role_override_pt",
            r"\b(voc[eê]|tu)\s+(é|es|agora\s+é|agora\s+es)\s+agora\b|\bvoc[eê]\s+agora\s+é\b",
        ),
        ("role_override_en", r"\byou\s+are\s+now\b|\bact\s+as\s+(a|an)\b|\bnew\s+persona\b"),
        (
            "execute_command",
            r"\b(execute|run|rode|executar)\b.{0,30}\b(command|comando|script|c[oó]digo|sql)\b",
        ),
        (
            "reveal_secrets",
            r"\b(reveal|print|show|mostre|revele|imprima)\b.{0,30}"
            r"\b(api[_ ]?key|senha|password|token|secret)",
        ),
        (
            "assistant_marker",
            r"</?\s*(system|assistant|human|user|tool)\s*>|\[(system|assistant)\]",
        ),
        ("developer_mode", r"\b(developer|dev|jailbreak|DAN)\s+mode\b"),
        ("delimiter_escape", r"</\s*noticia\s*>|<\s*noticia\b"),
    )
)


def normalise(text: str) -> str:
    """Fold unicode (full-width, zero-width characters) so pattern matching is not evaded."""
    folded = unicodedata.normalize("NFKC", text)
    return "".join(
        ch for ch in folded if unicodedata.category(ch) not in {"Cf", "Cc"} or ch in "\n\t"
    )


def find_injection(text: str) -> list[str]:
    """Return the labels of every injection pattern found (empty list when clean)."""
    candidate = normalise(text)
    return [label for label, pattern in INJECTION_PATTERNS if pattern.search(candidate)]
