"""Render a FileDoc as markdown. Links are relative to the page that will display them."""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

from markdown_serve.codedoc.model import FileDoc, Symbol

_MD_PATH = re.compile(r"(?<![\w./-])((?:[\w.+-]+/)*[\w.+-]+\.md)\b")
_TAG_LINE = re.compile(r"^[ \t]*[\\@](?P<tag>\w+)\b[ \t]*(?P<rest>.*)$")
_ENDCODE = re.compile(r"^[ \t]*[\\@]endcode\b")
_FENCE = re.compile(r"(```.*?```|`[^`\n]*`)", re.DOTALL)


def rel_href(from_file: str, to_file: str) -> str:
    """Relative link from the directory of ``from_file`` to ``to_file`` (posix, root-relative)."""
    start = posixpath.dirname(from_file.replace("\\", "/"))
    target = to_file.replace("\\", "/")
    href = posixpath.relpath(target, start or ".")
    return href


def strip_comment_markers(raw: str) -> str:
    text = raw.strip()
    if text.startswith("/**") or (text.startswith("/*") and not text.startswith("//")):
        if text.startswith("/**"):
            text = text[3:]
        else:
            text = text[2:]
        if text.endswith("*/"):
            text = text[:-2]
        lines = [re.sub(r"^\s*\*\s?", "", line) for line in text.splitlines()]
        return "\n".join(lines).strip()
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^\s*/{2,3}!?\s?", "", line)
        lines.append(line)
    return "\n".join(lines).strip()


def doxygen_to_markdown(text: str) -> str:
    """Turn doxygen commands into markdown. Unknown ``@tag`` lines stay as written."""
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        match = _TAG_LINE.match(lines[i])
        if match is None:
            out.append(lines[i])
            i += 1
            continue
        tag = match.group("tag").lower()
        rest = match.group("rest").strip()
        if tag in {"brief", "details", "file"}:
            if rest:
                out.append(rest)
        elif tag in {"param", "tparam"}:
            name, _, desc = rest.partition(" ")
            # ``[in] name`` and ``name`` both show up; keep the tail after a direction word.
            if name.startswith("[") and desc:
                name, desc = desc.split(None, 1) if " " in desc else (desc, "")
            label = "param" if tag == "param" else "tparam"
            piece = f"- **{label}** `{name}`"
            if desc:
                piece += f" — {desc}"
            out.append(piece)
        elif tag in {"return", "returns"}:
            out.append(f"**Returns:** {rest}".rstrip())
        elif tag == "note":
            out.append(f"**Note:** {rest}".rstrip())
        elif tag == "see":
            out.append(f"**See:** {rest}".rstrip())
        elif tag == "code":
            block: list[str] = []
            i += 1
            while i < len(lines) and _ENDCODE.match(lines[i]) is None:
                block.append(lines[i])
                i += 1
            out.append("```cpp")
            out.extend(block)
            out.append("```")
        else:
            out.append(lines[i])
        i += 1
    return "\n".join(out).strip()


def linkify_markdown_paths(text: str, from_file: str, root: Path | None) -> str:
    """Turn bare ``*.md`` paths that exist under ``root`` into links relative to ``from_file``.

    Existing markdown links and inline/fenced code are left alone. A path that already
    resolves relative to the source file stays written that way.
    """
    if root is None:
        return text

    def replace_prose(prose: str) -> str:
        def one(match: re.Match[str]) -> str:
            raw = match.group(1)
            start = match.start(1)
            # Already the target of a markdown link ``](path)`` or ``](path "title")``.
            if start >= 2 and prose[start - 2 : start] == "](":
                return raw
            src_dir = posixpath.dirname(from_file)
            relative = posixpath.normpath(posixpath.join(src_dir, raw)) if src_dir else raw
            if (root / relative).is_file():
                return f"[{raw}]({raw})"
            if (root / raw).is_file():
                return f"[{raw}]({rel_href(from_file, raw)})"
            return raw

        return _MD_PATH.sub(one, prose)

    parts = _FENCE.split(text)
    return "".join(part if part.startswith("`") else replace_prose(part) for part in parts)


def _slug(text: str, used: set[str]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "symbol"
    base = slug
    n = 2
    while slug in used:
        slug = f"{base}-{n}"
        n += 1
    used.add(slug)
    return slug


def _fence(signature: str, language: str = "cpp") -> str:
    body = signature.replace("```", "'''")
    tag = "pydoc" if language == "python" else "cppdoc"
    return f"```{tag}\n{body}\n```"


KIND_LABELS = {
    "namespace": "namespace",
    "class": "class",
    "struct": "struct",
    "union": "union",
    "enum": "enum",
    "enum_constant": "enumerator",
    "function": "function",
    "method": "method",
    "constructor": "constructor",
    "destructor": "destructor",
    "field": "field",
    "variable": "variable",
    "typedef": "typedef",
    "using": "using",
    "macro": "macro",
    "include_guard": "include guard",
}


def kind_badge(kind: str) -> str:
    """Empty span; the glyph comes from CSS so headings and the TOC keep their plain text."""
    key = kind if kind in KIND_LABELS else "unknown"
    label = KIND_LABELS.get(key, "symbol")
    return f'<span class="sym-kind" data-kind="{key}" title="{label}"></span>'


def _render_symbol(
    symbol: Symbol, from_file: str, level: int, used: set[str], root: Path | None, language: str = "cpp"
) -> list[str]:
    slug = _slug(symbol.qualified_name or symbol.name, used)
    heading = min(level, 6)
    doc = linkify_markdown_paths(doxygen_to_markdown(symbol.doc), from_file, root) if symbol.doc else ""
    defined = rel_href(from_file, symbol.file)
    if defined == ".":
        defined = posixpath.basename(symbol.file)
    line = symbol.line or 1
    lines = [
        f'<a id="{slug}"></a>',
        f"{'#' * heading} {kind_badge(symbol.kind)}{symbol.qualified_name or symbol.name}",
        "",
        _fence(symbol.signature or symbol.name, language),
        "",
    ]
    if doc:
        lines.append(doc)
        lines.append("")
    lines.append(f"Defined at [{symbol.file}:{line}]({defined}?line={line}).")
    lines.append("")
    for child in symbol.children:
        lines.extend(_render_symbol(child, from_file, level + 1, used, root, language))
    return lines


def _index_lines(symbols: list[Symbol], used: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for symbol in symbols:
        slug = used.get(symbol.usr) or used.get(symbol.qualified_name)
        label = symbol.qualified_name or symbol.name
        badge = kind_badge(symbol.kind)
        item = f"- {badge}[`{label}`](#{slug})" if slug else f"- {badge}`{label}`"
        if symbol.brief:
            item += f" — {symbol.brief}"
        lines.append(item)
        lines.extend(_index_lines(symbol.children, used))
    return lines


def _assign_slugs(symbols: list[Symbol], used: set[str], mapping: dict[str, str]) -> None:
    for symbol in symbols:
        slug = _slug(symbol.qualified_name or symbol.name, used)
        mapping[symbol.usr] = slug
        mapping[symbol.qualified_name] = slug
        _assign_slugs(symbol.children, used, mapping)


def render_file_markdown(doc: FileDoc, root: Path | None = None) -> str:
    """Markdown for one source file. Relative links use the source file's directory."""
    from_file = doc.rel_path
    used_ids: set[str] = set()
    lines = [
        f"# [{doc.rel_path}](/__file/{doc.rel_path})",
        "",
    ]
    if doc.file_doc:
        lines.append(linkify_markdown_paths(doxygen_to_markdown(doc.file_doc), from_file, root))
        lines.append("")
    if doc.includes:
        lines.append("## Imports" if doc.language == "python" else "## Includes")
        lines.append("")
        for include in doc.includes:
            lines.append(f"- [{include}]({rel_href(from_file, include)})")
        lines.append("")
    if doc.symbols:
        lines.append("## Index")
        lines.append("")
        # Slugs must match _render_symbol, which walks in the same order.
        preview: set[str] = set()
        preview_map: dict[str, str] = {}
        _assign_slugs(doc.symbols, preview, preview_map)
        lines.extend(_index_lines(doc.symbols, preview_map))
        lines.append("")
        for symbol in doc.symbols:
            lines.extend(_render_symbol(symbol, from_file, 2, used_ids, root, doc.language))
    return "\n".join(lines).rstrip() + "\n"


def render_index_markdown(language: str, files: list[str], index_rel: str) -> str:
    """Index page stored inside the cache. Links climb out to source paths."""
    groups: dict[str, list[str]] = {}
    for rel in sorted(files):
        groups.setdefault(posixpath.dirname(rel) or ".", []).append(rel)
    lines = [f"# {language} code documentation", ""]
    for directory in sorted(groups):
        lines.append(f"## {directory}")
        lines.append("")
        for rel in groups[directory]:
            lines.append(f"- [{rel}]({rel_href(index_rel, rel)})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
