"""Link names in signature fences to the symbol that defines them.

Generated pages fence signatures as ``cppdoc``. Older caches used ``cpp`` for
that same fence; the first code fence under a symbol heading is treated the
same way. ``@code`` examples stay ordinary ``cpp`` blocks.
"""

from __future__ import annotations

import html
import re
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from pygments.lexers import CppLexer
from pygments.token import Name, STANDARD_TYPES

from markdown_serve.codedoc.cache import cache_dir
from markdown_serve.codedoc.markdown import rel_href
from markdown_serve.render import render_markdown

_ANCHOR = re.compile(r'<a id="([^"]+)"></a>')
_TAG = re.compile(r"<[^>]+>")


def _heading_text(line: str) -> str:
    return _TAG.sub("", line.lstrip("#")).strip()
_FENCE_OPEN = re.compile(r"^```(cppdoc|cpp)[ \t]*$")
_IDENT = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*\b")
_KEYWORDS = frozenset(
    """
    const volatile void int bool char auto signed unsigned long short float double
    static inline virtual explicit constexpr consteval typename template class struct
    enum namespace public private protected operator sizeof return if else for while
    true false nullptr override final noexcept mutable friend using typedef decltype
    this new delete wchar_t char8_t char16_t char32_t extern register thread_local
    concept requires static_cast dynamic_cast reinterpret_cast const_cast
    """.split()
)
# ponytail: first 40 refs, raise the cap if a common type needs the rest
_REF_LIMIT = 40
_LEXER = CppLexer()
_INDEX_CACHE: dict[str, tuple[int, SymbolIndex]] = {}
_INDEX_LOCK = threading.Lock()


@dataclass(frozen=True)
class Ref:
    file: str
    anchor: str
    name: str


@dataclass
class SymbolIndex:
    """Definitions and the signatures that mention them, keyed by qualified name."""

    defs: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    tails: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)
    refs: dict[str, list[Ref]] = field(default_factory=dict)

    def lookup(self, name: str) -> tuple[str, str, str] | None:
        """Return ``(qualified name, file, anchor)`` when the name is unambiguous."""
        if "::" in name:
            return _prefer(name, self.defs.get(name) or [])
        if name in _KEYWORDS:
            return None
        exact = _prefer(name, self.defs.get(name) or [])
        if exact is not None:
            return exact
        return _prefer_tail(self.tails.get(name) or [])


def index_pages(pages: list[tuple[str, str]]) -> SymbolIndex:
    """Build an index from ``(source path, generated markdown)`` pairs."""
    index = SymbolIndex()
    signatures: list[tuple[str, str, str, str]] = []
    for rel, text in pages:
        _collect(rel, text, index, signatures)
    _fill_tails(index)
    seen: set[tuple[str, str, str]] = set()
    for rel, anchor, by, body in signatures:
        for match in _IDENT.finditer(body):
            hit = index.lookup(match.group(0))
            if hit is None:
                continue
            key, _file, _def_anchor = hit
            if rel == _file and anchor == _def_anchor:
                continue
            marker = (key, rel, anchor)
            if marker in seen:
                continue
            seen.add(marker)
            index.refs.setdefault(key, []).append(Ref(rel, anchor, by))
    for items in index.refs.values():
        items.sort(key=lambda item: (item.file, item.name, item.anchor))
    return index


def load_symbol_index(root: Path) -> SymbolIndex:
    """Index the generated pages under the project cache. Cached on the manifest mtime."""
    cache = cache_dir(root)
    manifest = cache / "manifest.json"
    try:
        stamp = manifest.stat().st_mtime_ns
    except OSError:
        stamp = 0
    key = str(cache.resolve()) if cache.exists() else str(cache)
    with _INDEX_LOCK:
        cached = _INDEX_CACHE.get(key)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        pages = _read_pages(cache)
        built = index_pages(pages)
        _INDEX_CACHE[key] = (stamp, built)
        return built


def render_codedoc_page(text: str, from_file: str, index: SymbolIndex) -> str:
    """Render a generated page, with signature names linked to their definitions."""
    lines = text.splitlines()
    out: list[str] = []
    blocks: dict[str, str] = {}
    i = 0
    pending_id: str | None = None
    current_id: str | None = None
    current_name: str | None = None
    expect_signature = False
    while i < len(lines):
        line = lines[i]
        anchor = _ANCHOR.fullmatch(line.strip())
        if anchor:
            pending_id = anchor.group(1)
            out.append(line)
            i += 1
            continue
        if line.startswith("#"):
            current_name = _heading_text(line) if pending_id else current_name
            current_id = pending_id if pending_id else current_id
            expect_signature = pending_id is not None
            pending_id = None
            out.append(line)
            i += 1
            continue
        opened = _FENCE_OPEN.match(line.strip())
        if opened and (opened.group(1) == "cppdoc" or expect_signature):
            body: list[str] = []
            i += 1
            while i < len(lines) and lines[i].strip() != "```":
                body.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            expect_signature = False
            token = f"CPPDOCPLACEHOLDER{uuid.uuid4().hex}END"
            blocks[token] = _highlight("\n".join(body), from_file, index, current_id)
            out.append("")
            out.append(token)
            out.append("")
            continue
        if pending_id and line.strip():
            pending_id = None
        out.append(line)
        if line.startswith("Defined at ") and current_name and current_id:
            ref_line = _refs_line(current_name, from_file, current_id, index)
            if ref_line:
                out.append("")
                out.append(ref_line)
        i += 1
    rendered = render_markdown("\n".join(out).rstrip() + "\n")
    for token, block in blocks.items():
        rendered = rendered.replace(f"<p>{token}</p>", block)
        rendered = rendered.replace(token, block)
    return rendered


def _prefer(name: str, locs: list[tuple[str, str]]) -> tuple[str, str, str] | None:
    files = {loc[0] for loc in locs}
    if len(files) != 1 or not locs:
        return None
    return name, locs[0][0], locs[0][1]


def _prefer_tail(entries: list[tuple[str, str, str]]) -> tuple[str, str, str] | None:
    """Bare names pick the shortest match (the type, not ``Type::Type``) when that one is unique."""
    if not entries:
        return None
    depth = min(entry[0].count("::") for entry in entries)
    chosen = [entry for entry in entries if entry[0].count("::") == depth]
    files = {entry[1] for entry in chosen}
    if len(files) != 1:
        return None
    return min(chosen, key=lambda entry: entry[0])


def _fill_tails(index: SymbolIndex) -> None:
    for name, locs in index.defs.items():
        tail = name.rsplit("::", 1)[-1]
        if not tail or tail in _KEYWORDS:
            continue
        bucket = index.tails.setdefault(tail, [])
        for file, anchor in locs:
            bucket.append((name, file, anchor))


def _collect(rel: str, text: str, index: SymbolIndex, signatures: list[tuple[str, str, str, str]]) -> None:
    lines = text.splitlines()
    i = 0
    pending_id: str | None = None
    current_id: str | None = None
    current_name: str | None = None
    expect_signature = False
    while i < len(lines):
        line = lines[i]
        anchor = _ANCHOR.fullmatch(line.strip())
        if anchor:
            pending_id = anchor.group(1)
            i += 1
            continue
        if line.startswith("#"):
            if pending_id:
                current_name = _heading_text(line)
                current_id = pending_id
                index.defs.setdefault(current_name, []).append((rel, current_id))
                expect_signature = True
            pending_id = None
            i += 1
            continue
        opened = _FENCE_OPEN.match(line.strip())
        if opened and current_id and current_name and (opened.group(1) == "cppdoc" or expect_signature):
            body: list[str] = []
            i += 1
            while i < len(lines) and lines[i].strip() != "```":
                body.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            expect_signature = False
            signatures.append((rel, current_id, current_name, "\n".join(body)))
            continue
        if pending_id and line.strip():
            pending_id = None
        i += 1


def _read_pages(cache: Path) -> list[tuple[str, str]]:
    if not cache.is_dir():
        return []
    pages: list[tuple[str, str]] = []
    for lang_dir in sorted(path for path in cache.iterdir() if path.is_dir()):
        for path in sorted(lang_dir.rglob("*.md")):
            if path.name == "index.md":
                continue
            rel = path.relative_to(lang_dir).as_posix()
            if not rel.endswith(".md"):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            pages.append((rel[:-3], text))
    return pages


def _refs_line(name: str, from_file: str, anchor: str, index: SymbolIndex) -> str:
    hit = index.lookup(name)
    key = hit[0] if hit is not None else name
    items = [
        item
        for item in index.refs.get(key) or []
        if not (item.file == from_file and item.anchor == anchor)
    ]
    if not items:
        return ""
    shown = items[:_REF_LIMIT]
    links = ", ".join(f"[`{_md_label(item.name)}`]({_href(from_file, item.file, item.anchor)})" for item in shown)
    extra = f" … and {len(items) - _REF_LIMIT} more" if len(items) > _REF_LIMIT else ""
    return f"Referenced by {links}.{extra}"


def _md_label(name: str) -> str:
    return name.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _href(from_file: str, target: str, anchor: str) -> str:
    if from_file == target:
        return f"#{anchor}"
    return f"{rel_href(from_file, target)}#{anchor}"


def _highlight(source: str, from_file: str, index: SymbolIndex, current_anchor: str | None) -> str:
    parts: list[str] = []
    buf: list[tuple[str, str]] = []
    state = "idle"

    def flush() -> None:
        nonlocal state
        if not buf:
            state = "idle"
            return
        text = "".join(value for _cls, value in buf)
        href = _link_href(text, from_file, index, current_anchor)
        body = "".join(_span(cls, value) for cls, value in buf)
        if href:
            parts.append(f'<a class="cppdoc-def" href="{html.escape(href, quote=True)}">{body}</a>')
        else:
            parts.append(body)
        buf.clear()
        state = "idle"

    for ttype, value in _LEXER.get_tokens(source):
        cls = _css(ttype)
        is_name = ttype in Name
        if state == "idle":
            if is_name:
                buf.append((cls, value))
                state = "ident"
            else:
                parts.append(_span(cls, value))
        elif state == "ident":
            if value == ":":
                buf.append((cls, value))
                state = "colon"
            else:
                flush()
                if is_name:
                    buf.append((cls, value))
                    state = "ident"
                else:
                    parts.append(_span(cls, value))
        elif state == "colon":
            if value == ":":
                buf.append((cls, value))
                state = "need"
            else:
                flush()
                if is_name:
                    buf.append((cls, value))
                    state = "ident"
                else:
                    parts.append(_span(cls, value))
        elif state == "need":
            if is_name:
                buf.append((cls, value))
                state = "ident"
            else:
                flush()
                parts.append(_span(cls, value))
    flush()
    return f'<div class="highlight"><pre><span></span>{"".join(parts)}</pre></div>'


def _link_href(name: str, from_file: str, index: SymbolIndex, current_anchor: str | None) -> str | None:
    hit = index.lookup(name)
    if hit is None:
        return None
    _key, file, anchor = hit
    if file == from_file and anchor == current_anchor:
        return None
    return _href(from_file, file, anchor)


def _css(ttype) -> str:
    while ttype and ttype not in STANDARD_TYPES:
        ttype = ttype.parent
    return STANDARD_TYPES.get(ttype, "")


def _span(cls: str, value: str) -> str:
    text = html.escape(value)
    if not cls:
        return text
    return f'<span class="{cls}">{text}</span>'
