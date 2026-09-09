"""Markdown → HTML rendering tests."""

from __future__ import annotations

from textwrap import dedent

import pytest

from markdown_serve.render import render_diagram, render_markdown


@pytest.mark.parametrize(
    ("markdown", "expected"),
    [
        (
            "Hello **world**.",
            "<p>Hello <strong>world</strong>.</p>",
        ),
        (
            dedent(
                """\
                - a
                  - b
                    - c
                - d
                """
            ),
            dedent(
                """\
                <ul>
                <li>a<ul>
                <li>b<ul>
                <li>c</li>
                </ul>
                </li>
                </ul>
                </li>
                <li>d</li>
                </ul>"""
            ),
        ),
        (
            dedent(
                """\
                1. one
                   1. two
                   2. three
                2. four
                """
            ),
            dedent(
                """\
                <ol>
                <li>one<ol>
                <li>two</li>
                <li>three</li>
                </ol>
                </li>
                <li>four</li>
                </ol>"""
            ),
        ),
        (
            dedent(
                """\
                - item
                  - nested under item
                - another
                """
            ),
            dedent(
                """\
                <ul>
                <li>item<ul>
                <li>nested under item</li>
                </ul>
                </li>
                <li>another</li>
                </ul>"""
            ),
        ),
        (
            dedent(
                """\
                1. Ordered

                * Unordered
                """
            ),
            dedent(
                """\
                <ol>
                <li>Ordered</li>
                </ol>
                <ul>
                <li>Unordered</li>
                </ul>"""
            ),
        ),
        (
            "# Title\n\n## Section",
            (
                '<h1 id="title">Title'
                '<a class="headerlink" href="#title" title="Permanent link">&para;</a>'
                "</h1>\n"
                '<h2 id="section">Section'
                '<a class="headerlink" href="#section" title="Permanent link">&para;</a>'
                "</h2>"
            ),
        ),
        (
            dedent(
                """\
                | a | b |
                | --- | --- |
                | 1 | 2 |
                """
            ),
            dedent(
                """\
                <table>
                <thead>
                <tr>
                <th>a</th>
                <th>b</th>
                </tr>
                </thead>
                <tbody>
                <tr>
                <td>1</td>
                <td>2</td>
                </tr>
                </tbody>
                </table>"""
            ),
        ),
        (
            "line one\nline two",
            "<p>line one\nline two</p>",
        ),
        (
            "para one\n\npara two",
            "<p>para one</p>\n<p>para two</p>",
        ),
        (
            dedent(
                """\
                - `/api` - Accepts query params and a path to the asset, then
                  enqueues a job and returns its id
                  TODO: document supported params.
                """
            ),
            dedent(
                """\
                <ul>
                <li><code>/api</code> - Accepts query params and a path to the asset, then
                  enqueues a job and returns its id
                  TODO: document supported params.</li>
                </ul>"""
            ),
        ),
    ],
    ids=[
        "bold",
        "nested-unordered",
        "nested-ordered",
        "nested-under-item",
        "sane-list-separation",
        "headers-toc",
        "table",
        "soft-linebreak-no-br",
        "blank-line-paragraphs",
        "list-soft-linebreak-no-br",
    ],
)
def test_render_markdown_html(markdown: str, expected: str) -> None:
    assert render_markdown(markdown) == expected


@pytest.mark.parametrize(
    ("fence", "kind", "source"),
    [
        ("mermaid", "mermaid", "flowchart LR\n  A --> B"),
        ("plantuml", "plantuml", "@startuml\nAlice -> Bob\n@enduml"),
        ("puml", "plantuml", "@startuml\nA -> B\n@enduml"),
    ],
    ids=["mermaid", "plantuml", "puml-alias"],
)
def test_render_diagram_fences(fence: str, kind: str, source: str) -> None:
    markdown = f"```{fence}\n{source}\n```"
    html = render_markdown(markdown)

    assert f'class="diagram diagram-{kind}"' in html
    assert '<pre class="diagram-source">' in html
    for line in source.splitlines():
        escaped = (
            line.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        assert escaped in html
    assert "DIAGRAMPLACEHOLDER" not in html
    assert "```" not in html


@pytest.mark.parametrize(
    ("kind", "expected_kind"),
    [("mermaid", "mermaid"), ("plantuml", "plantuml"), ("puml", "plantuml"), ("Mermaid", "mermaid")],
)
def test_render_diagram_standalone(kind: str, expected_kind: str) -> None:
    source = "\nA -> B: <hi>\n\n"
    html = render_diagram(source, kind)
    assert html == (
        f'<div class="diagram diagram-{expected_kind}">'
        '<pre class="diagram-source">A -&gt; B: &lt;hi&gt;</pre>'
        "</div>"
    )


def test_render_diagram_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError):
        render_diagram("x", "graphviz")


def test_render_fenced_code_highlight() -> None:
    html = render_markdown("```python\nprint(1)\n```")
    assert '<div class="highlight">' in html
    assert "<pre>" in html
    assert "print" in html
