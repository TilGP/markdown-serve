"""Python cache build using the stdlib AST."""

from __future__ import annotations

from pathlib import Path

from markdown_serve.codedoc.builder import build
from markdown_serve.codedoc.xrefs import index_pages, render_codedoc_page


def _project(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text('"""The package."""\n', encoding="utf-8")
    (pkg / "helpers.py").write_text(
        'def help_name() -> str:\n    """Return a label."""\n    return "x"\n',
        encoding="utf-8",
    )
    (pkg / "widget.py").write_text(
        "\n".join(
            [
                '"""Widgets."""',
                "from .helpers import help_name",
                "",
                "def cached(fn):",
                "    return fn",
                "",
                "@cached",
                "class Widget:",
                '    """A widget."""',
                "",
                "    def area(self, scale: int = 1) -> int:",
                '        """Area of the widget."""',
                "        return scale",
                "",
                "async def load(path: str) -> Widget:",
                '    """Load one widget."""',
                "    return Widget()",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "bad.py").write_text("def (\n", encoding="utf-8")
    third = tmp_path / "third-party"
    third.mkdir()
    (third / "skip.py").write_text("def skip():\n    return 1\n", encoding="utf-8")


def test_build_documents_modules_and_skips_ignored(tmp_path: Path) -> None:
    _project(tmp_path)
    result = build(tmp_path, languages=["python"], jobs=1, force=True)
    assert result["errors"] == []
    cache = tmp_path / ".cache" / "markdown-serve" / "python"
    page = (cache / "pkg" / "widget.py.md").read_text(encoding="utf-8")
    assert "Widgets." in page
    assert "## Imports" in page
    assert "[pkg/helpers.py](helpers.py)" in page
    assert 'data-kind="class" title="class"></span>pkg.widget.Widget' in page
    assert "@cached\nclass Widget" in page
    assert "def area(self, scale: int=1) -> int" in page
    assert "Area of the widget." in page
    assert "async def load(path: str) -> Widget" in page
    assert "```pydoc" in page
    assert "Could not parse" in (cache / "bad.py.md").read_text(encoding="utf-8")
    assert not (cache / "third-party" / "skip.py.md").exists()
    init = (cache / "pkg" / "__init__.py.md").read_text(encoding="utf-8")
    assert "The package." in init

    again = build(tmp_path, languages=["python"], jobs=2)
    assert again["errors"] == []


def test_pydoc_signature_links_a_dotted_name(tmp_path: Path) -> None:
    _project(tmp_path)
    build(tmp_path, languages=["python"], jobs=1, force=True)
    cache = tmp_path / ".cache" / "markdown-serve" / "python"
    widget = (cache / "pkg" / "widget.py.md").read_text(encoding="utf-8")
    use = "\n".join(
        [
            '<a id="run"></a>',
            "## run",
            "",
            "```pydoc",
            "def run() -> pkg.widget.Widget",
            "```",
            "",
            "Defined at [app.py:1](app.py?line=1).",
            "",
        ]
    )
    index = index_pages([("pkg/widget.py", widget), ("app.py", use)])
    html = render_codedoc_page(use, "app.py", index)
    assert 'href="pkg/widget.py#pkg-widget-widget"' in html
    html = render_codedoc_page(widget, "pkg/widget.py", index)
    assert 'href="#pkg-widget-widget"' in html
