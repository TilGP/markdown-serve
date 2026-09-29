"""Generated markdown: doxygen commands and links relative to the page that shows them."""

from __future__ import annotations

from pathlib import Path

from markdown_serve.codedoc.markdown import (
    doxygen_to_markdown,
    rel_href,
    render_file_markdown,
    render_index_markdown,
)
from markdown_serve.codedoc.model import FileDoc, Symbol


def _symbol(**overrides) -> Symbol:
    data = dict(
        kind="function",
        name="add",
        qualified_name="add",
        signature="int add(int a, int b)",
        doc="Adds two integers.\nSee api/async-search.md for the flow.\nSee [design](../docs/design.md).",
        brief="Adds two integers.",
        file="libs/grpcsvr/src/config.hpp",
        line=42,
        end_line=44,
        access="",
        usr="fn-add",
    )
    data.update(overrides)
    return Symbol(**data)


def test_doxygen_commands() -> None:
    text = doxygen_to_markdown(
        "\n".join(
            [
                "@brief Build a cache",
                "@param root Project root",
                "@tparam T value type",
                "@return nothing useful",
                "@note keep it local",
                "@see other.hpp",
                "@code",
                "int x = 1;",
                "@endcode",
                "@unknown stays",
            ]
        )
    )
    assert "Build a cache" in text
    assert "**param** `root`" in text
    assert "**tparam** `T`" in text
    assert "**Returns:** nothing useful" in text
    assert "**Note:** keep it local" in text
    assert "**See:** other.hpp" in text
    assert "```cpp" in text
    assert "int x = 1;" in text
    assert "@unknown stays" in text


def test_source_page_links_are_relative_to_the_source_file(tmp_path: Path) -> None:
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "async-search.md").write_text("# async\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "design.md").write_text("# design\n", encoding="utf-8")
    doc = FileDoc(
        rel_path="libs/grpcsvr/src/config.hpp",
        language="cpp",
        file_doc="",
        symbols=[_symbol()],
        includes=["libs/ngn/src/rules.hpp"],
    )
    text = render_file_markdown(doc, tmp_path)
    assert "# [libs/grpcsvr/src/config.hpp](/__file/libs/grpcsvr/src/config.hpp)" in text
    assert "[api/async-search.md](../../../api/async-search.md)" in text
    assert "[design](../docs/design.md)" in text
    assert "[libs/ngn/src/rules.hpp](../../ngn/src/rules.hpp)" in text
    assert "```cppdoc\nint add(int a, int b)\n```" in text
    badge = '<span class="sym-kind" data-kind="function" title="function"></span>'
    assert f"## {badge}add" in text
    assert f"- {badge}[`add`](#add)" in text
    assert "Defined at [libs/grpcsvr/src/config.hpp:42](config.hpp?line=42)." in text
    assert ".cache/" not in text


def test_index_links_climb_out_of_the_cache() -> None:
    index = ".cache/markdown-serve/cpp/index.md"
    text = render_index_markdown("cpp", ["libs/grpcsvr/src/config.hpp"], index)
    assert f"[libs/grpcsvr/src/config.hpp]({rel_href(index, 'libs/grpcsvr/src/config.hpp')})" in text
    assert "../../../libs/grpcsvr/src/config.hpp" in text
