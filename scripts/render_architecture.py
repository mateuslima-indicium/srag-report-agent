"""Render the Mermaid diagram in docs/architecture.md to docs/architecture.pdf.

Strategies, in order: mermaid.ink PDF endpoint; mermaid.ink PNG converted to PDF with
Pillow; a matplotlib box diagram drawn locally (works offline). The PDF must always exist.
"""

from __future__ import annotations

import base64
import io
import re
import sys
from pathlib import Path

import httpx

DOCS = Path(__file__).resolve().parents[1] / "docs"
SOURCE = DOCS / "architecture.md"
TARGET = DOCS / "architecture.pdf"
MERMAID_INK = "https://mermaid.ink"
TIMEOUT = 60.0


def extract_mermaid(markdown: str) -> str:
    match = re.search(r"```mermaid\n(.*?)```", markdown, re.DOTALL)
    if not match:
        msg = f"No mermaid block found in {SOURCE}"
        raise ValueError(msg)
    return match.group(1)


def encode(diagram: str) -> str:
    return base64.urlsafe_b64encode(diagram.encode("utf-8")).decode("ascii")


def via_mermaid_ink_pdf(diagram: str) -> bytes:
    response = httpx.get(f"{MERMAID_INK}/pdf/{encode(diagram)}?fit", timeout=TIMEOUT)
    response.raise_for_status()
    if not response.content.startswith(b"%PDF"):
        msg = "mermaid.ink did not return a PDF"
        raise ValueError(msg)
    return response.content


def via_mermaid_ink_image(diagram: str) -> bytes:
    from PIL import Image

    response = httpx.get(
        f"{MERMAID_INK}/img/{encode(diagram)}?type=png&width=2400", timeout=TIMEOUT
    )
    response.raise_for_status()
    image = Image.open(io.BytesIO(response.content)).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PDF", resolution=150)
    return buffer.getvalue()


def via_matplotlib() -> bytes:
    """Offline fallback: a simplified box-and-arrow version of the same architecture."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    boxes = {
        "cli": (0.5, 5.0, "CLI\nsrag-agent report"),
        "graph": (
            3.2,
            5.0,
            "Orquestrador LangGraph\ncollect_metrics → fetch_news →\n"
            "analyze ⇄ run_tools →\nwrite_report → validate → render",
        ),
        "llm": (3.2, 7.6, "LLM\nClaude (Anthropic API)"),
        "tools": (6.4, 5.0, "Tools LangChain\nmétricas · run_readonly_sql · notícias"),
        "db": (9.4, 6.3, "DuckDB (read-only)\nParquet de-identificado"),
        "news": (9.4, 3.7, "Google News RSS\n(+ Tavily opcional)"),
        "guard": (
            6.4,
            2.4,
            "Guardrails\nsql · injeção · numérico ·\ncaveats · clínico · PII · orçamentos",
        ),
        "audit": (3.2, 2.4, "Auditoria JSONL\naudit/run-*.jsonl"),
        "report": (0.5, 2.4, "Relatório\nMarkdown + 2 PNG"),
    }
    edges = [
        ("cli", "graph"),
        ("graph", "llm"),
        ("graph", "tools"),
        ("tools", "db"),
        ("tools", "news"),
        ("tools", "guard"),
        ("graph", "guard"),
        ("graph", "audit"),
        ("graph", "report"),
    ]
    fig, ax = plt.subplots(figsize=(14, 9))
    ax.set_xlim(-0.8, 11.6)
    ax.set_ylim(1.2, 9.0)
    ax.axis("off")
    ax.set_title("srag-report-agent: arquitetura", fontsize=16, fontweight="bold", loc="left")
    for x, y, label in boxes.values():
        ax.add_patch(
            FancyBboxPatch(
                (x - 1.1, y - 0.7),
                2.2,
                1.4,
                boxstyle="round,pad=0.08",
                fc="#eef3fb",
                ec="#2a78d6",
                lw=1.5,
            )
        )
        ax.text(x, y, label, ha="center", va="center", fontsize=9)
    for start, end in edges:
        (x1, y1, _), (x2, y2, _) = boxes[start], boxes[end]
        ax.add_patch(
            FancyArrowPatch(
                (x1, y1),
                (x2, y2),
                arrowstyle="->",
                mutation_scale=14,
                color="#52514e",
                shrinkA=42,
                shrinkB=42,
            )
        )
    buffer = io.BytesIO()
    fig.savefig(buffer, format="pdf")
    plt.close(fig)
    return buffer.getvalue()


def main() -> None:
    diagram = extract_mermaid(SOURCE.read_text(encoding="utf-8"))
    strategies = (
        ("mermaid.ink/pdf", lambda: via_mermaid_ink_pdf(diagram)),
        ("mermaid.ink/img -> PDF", lambda: via_mermaid_ink_image(diagram)),
        ("matplotlib (offline)", via_matplotlib),
    )
    for name, strategy in strategies:
        try:
            TARGET.write_bytes(strategy())
        except Exception as error:  # noqa: BLE001 - try the next strategy
            print(f"{name}: failed ({type(error).__name__}: {error})", file=sys.stderr)
            continue
        print(f"{name}: wrote {TARGET} ({TARGET.stat().st_size / 1024:.0f} kB)")
        return
    sys.exit("could not render docs/architecture.pdf")


if __name__ == "__main__":
    main()
