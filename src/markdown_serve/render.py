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
    # Replaces sane_lists; 2-space nesting matches GFM/CommonMark editors.
    "mdx_truly_sane_lists",
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
    "mdx_truly_sane_lists": {
        "nested_indent": 2,
        "truly_sane": True,
    },
}

# Extract diagram fences before Markdown/codehilite can rewrite them.
DIAGRAM_FENCE_RE = re.compile(
    r"^```(mermaid|plantuml|puml)[ \t]*\n(.*?)(?:\n)?^```[ \t]*$",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)


def render_diagram(source: str, kind: str) -> str:
    """Wrap raw diagram source so the browser can render it (Mermaid/PlantUML).

    Also used for standalone ``.mmd`` / ``.puml`` files opened directly.
    """
    kind = kind.lower()
    if kind == "puml":
        kind = "plantuml"
    if kind not in {"mermaid", "plantuml"}:
        raise ValueError(f"Unknown diagram kind: {kind}")
    body = html.escape(source.strip("\n"))
    return (
        f'<div class="diagram diagram-{kind}">'
        f'<pre class="diagram-source">{body}</pre>'
        f"</div>"
    )


def _extract_diagrams(text: str) -> tuple[str, dict[str, str]]:
    diagrams: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        token = f"DIAGRAMPLACEHOLDER{uuid.uuid4().hex}END"
        diagrams[token] = render_diagram(match.group(2), match.group(1))
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


def pygments_css(*, light_style: str = "default", dark_style: str = "nord") -> str:
    light = HtmlFormatter(style=light_style).get_style_defs(".highlight")
    dark = HtmlFormatter(style=dark_style).get_style_defs('html[data-theme="dark"] .highlight')
    # Keep token colors from Pygments; force containers onto our theme surface
    # so light style backgrounds never peek behind rounded <pre> corners.
    override = """
#content .highlight,
#content .highlight pre,
html[data-theme="dark"] #content .highlight,
html[data-theme="dark"] #content .highlight pre {
  background: var(--code-bg) !important;
}
#content .highlight {
  border-radius: 8px;
  overflow: hidden;
}
#content .highlight pre {
  margin: 0;
  border: none;
  border-radius: 0;
}
"""
    return f"{light}\n{dark}\n{override}"
