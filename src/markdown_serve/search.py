"""Full-text content search over markdown files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# path -> (mtime_ns, size, text)
_FILE_CACHE: dict[str, tuple[int, int, str]] = {}

_BOUNDARY = set("/-_ .")


def _read_cached(path: Path) -> str | None:
    try:
        st = path.stat()
    except OSError:
        return None
    key = str(path)
    hit = _FILE_CACHE.get(key)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        _FILE_CACHE.pop(key, None)
        return None
    _FILE_CACHE[key] = (st.st_mtime_ns, st.st_size, text)
    return text


def prune_cache(keep: set[str]) -> None:
    for key in list(_FILE_CACHE):
        if key not in keep:
            del _FILE_CACHE[key]


def score_subsequence(query: str, text: str) -> float:
    """Match query as a subsequence of text; higher is better. -1 if no match."""
    if not query:
        return 1.0
    qi = 0
    score = 0.0
    prev = -2
    run = 0
    for i, ch in enumerate(text):
        if qi >= len(query):
            break
        if ch != query[qi]:
            continue
        run = run + 1 if i == prev + 1 else 1
        score += 1 + run * 3
        if i == 0 or (i > 0 and text[i - 1] in _BOUNDARY):
            score += 5
        prev = i
        qi += 1
    return score if qi == len(query) else -1.0


def find_subsequence_span(query: str, text: str) -> tuple[int, int] | None:
    qi = 0
    start = -1
    for i, ch in enumerate(text):
        if qi >= len(query):
            break
        if ch != query[qi]:
            continue
        if start < 0:
            start = i
        qi += 1
        if qi == len(query):
            return start, i + 1
    return None


def content_exact_score(query: str, text: str) -> float:
    if not query:
        return 1.0
    q = query.lower()
    full = text.lower()
    idx = full.find(q)
    if idx < 0:
        return -1.0
    score = 1000.0 - min(idx, 500)
    if idx == 0 or full[idx - 1].isspace():
        score += 50
    return score


def content_score(query: str, text: str) -> float:
    if not query:
        return 1.0
    if query.startswith("'"):
        return content_exact_score(query[1:], text)
    return score_subsequence(query.lower(), text.lower())


def content_match_span(query: str, text: str) -> tuple[int, int] | None:
    raw = query[1:] if query.startswith("'") else query
    if not raw:
        return None
    q = raw.lower()
    full = text.lower()
    if query.startswith("'"):
        idx = full.find(q)
        if idx < 0:
            return None
        return idx, idx + len(q)
    return find_subsequence_span(q, full)


def offset_to_line(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def make_snippet(text: str, start: int, end: int, radius: int = 42) -> str:
    from_ = max(0, start - radius)
    to = min(len(text), end + radius)
    snip = re.sub(r"\s+", " ", text[from_:to]).strip()
    if from_ > 0:
        snip = "…" + snip
    if to < len(text):
        snip = snip + "…"
    return snip


def content_snippet(query: str, text: str) -> tuple[str, int]:
    """Return (snippet, 1-based line number of the best match)."""
    span = content_match_span(query, text)
    if not span:
        preview = re.sub(r"\s+", " ", text[:80]).strip()
        if len(text) > 80:
            preview += "…"
        return preview, 1
    start, end = span
    return make_snippet(text, start, end), offset_to_line(text, start)


def search_markdown(
    root: Path,
    rel_paths: list[str],
    query: str,
    *,
    limit: int = 80,
) -> list[dict[str, Any]]:
    q = query.strip()
    if not q:
        return []

    root = root.resolve()
    keep: set[str] = set()
    hits: list[dict[str, Any]] = []

    for rel in rel_paths:
        path = (root / rel).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        keep.add(str(path))
        text = _read_cached(path)
        if text is None:
            continue
        score = content_score(q, text)
        if score < 0:
            continue
        snippet, line = content_snippet(q, text)
        hits.append(
            {
                "path": rel,
                "score": score,
                "snippet": snippet,
                "line": line,
            }
        )

    prune_cache(keep)
    hits.sort(key=lambda h: (-h["score"], h["path"]))
    return hits[:limit]
