"""Markdown to HTML rendering."""

from __future__ import annotations

import html
import re
import uuid

import markdown
from pygments.formatters import HtmlFormatter

EXTENSIONS = [
    "fenced_code",
    "codehilite",
    "tables",
    "toc",
    "nl2br",
    "sane_lists",
    "smarty",
]

EXTENSION_CONFIGS = {
    "codehilite": {
        "css_class": "highlight",
        "guess_lang": True,
        "linenums": False,
    },
    "toc": {
        "permalink": True,
    },
}

# Extract diagram fences before Markdown/codehilite can rewrite them.
DIAGRAM_FENCE_RE = re.compile(
    r"^```(mermaid|plantuml|puml)[ \t]*\n(.*?)(?:\n)?^```[ \t]*$",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)


def _extract_diagrams(text: str) -> tuple[str, dict[str, str]]:
    diagrams: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        kind = match.group(1).lower()
        if kind == "puml":
            kind = "plantuml"
        source = match.group(2).strip("\n")
        token = f"DIAGRAMPLACEHOLDER{uuid.uuid4().hex}END"
        diagrams[token] = (
            f'<div class="diagram diagram-{kind}">'
            f'<pre class="diagram-source">{html.escape(source)}</pre>'
            f"</div>"
        )
        return f"\n\n{token}\n\n"

    return DIAGRAM_FENCE_RE.sub(replace, text), diagrams


def render_markdown(text: str) -> str:
    text, diagrams = _extract_diagrams(text)
    rendered = markdown.markdown(
        text,
        extensions=EXTENSIONS,
        extension_configs=EXTENSION_CONFIGS,
    )
    for token, block in diagrams.items():
        # Markdown may wrap the bare token in <p>…</p>
        rendered = rendered.replace(f"<p>{token}</p>", block)
        rendered = rendered.replace(token, block)
    return rendered


def pygments_css() -> str:
    return HtmlFormatter(style="default").get_style_defs(".highlight")
