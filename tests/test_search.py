"""Content search unit tests."""

from __future__ import annotations

from pathlib import Path

from markdown_serve.search import (
    content_score,
    content_snippet,
    offset_to_line,
    search_markdown,
)


def test_exact_prefix_finds_substring():
    text = "alpha\nunique-zebra-token lives here\nomega\n"
    assert content_score("'zebra-token", text) > 0
    assert content_score("'missing-token", text) < 0


def test_fuzzy_subsequence_match():
    text = "Installation instructions for markdown-serve\n"
    assert content_score("instms", text) > 0
    assert content_score("zzzqqq", text) < 0


def test_snippet_and_line_number():
    text = "line one\nline two has needle here\nline three\n"
    snippet, line = content_snippet("'needle", text)
    assert line == 2
    assert "needle" in snippet


def test_offset_to_line():
    text = "a\nb\nc"
    assert offset_to_line(text, 0) == 1
    assert offset_to_line(text, 2) == 2
    assert offset_to_line(text, 4) == 3


def test_search_markdown_returns_ranked_hits(tmp_path: Path):
    (tmp_path / "a.md").write_text("# Hello\n\nunique-zebra-token appears here\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# Other\n\nnothing special\n", encoding="utf-8")
    (tmp_path / "c.md").write_text("also mentions unique-zebra-token early\n", encoding="utf-8")

    hits = search_markdown(tmp_path, ["a.md", "b.md", "c.md"], "'unique-zebra-token")
    paths = [h["path"] for h in hits]
    assert paths == ["a.md", "c.md"]
    assert all("line" in h and "snippet" in h and "score" in h for h in hits)
    assert hits[0]["score"] >= hits[1]["score"]
    assert "unique-zebra-token" in hits[0]["snippet"]
    assert hits[0]["line"] >= 1
