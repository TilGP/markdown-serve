"""C++ cache build. Skipped when the libclang bindings or library are missing."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from markdown_serve.codedoc.builder import build
from markdown_serve.codedoc.cpp.backend import find_libclang


pytest.importorskip("clang.cindex")
if find_libclang() is None:
    pytest.skip("libclang shared library not found", allow_module_level=True)


def _project(tmp_path: Path) -> None:
    include = tmp_path / "include"
    src = tmp_path / "src"
    docs = tmp_path / "docs"
    third = tmp_path / "third-party"
    for directory in (include, src, docs, third):
        directory.mkdir()
    (docs / "notes.md").write_text("# notes\n", encoding="utf-8")
    (include / "hello.hpp").write_text(
        "\n".join(
            [
                "#pragma once",
                "/// Adds two integers.",
                "/// See docs/notes.md for the design.",
                "int add(int a, int b);",
                "",
                "// Counts items.",
                "int count();",
                "",
                "class Box {",
                "public:",
                "  /// Width in pixels.",
                "  int width;",
                "private:",
                "  int secret;",
                "};",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (include / "orphan.hpp").write_text(
        "#ifndef ORPHAN_HPP\n#define ORPHAN_HPP\n#define ORPHAN_LIMIT 3\n/// Standalone orphan.\nstruct Orphan {};\n#endif\n",
        encoding="utf-8",
    )
    (src / "hello.cpp").write_text(
        "\n".join(
            [
                '#include "include/hello.hpp"',
                "namespace {",
                "/// Hidden helper.",
                "int helper();",
                "}",
                "int add(int a, int b) { return a + b; }",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (third / "skip.cpp").write_text("int skip;\n", encoding="utf-8")
    compiler = shutil.which("clang++") or "clang++"
    include_flag = str(tmp_path)

    def entry(path: Path) -> dict:
        return {
            "directory": str(tmp_path),
            "file": str(path),
            "arguments": [compiler, "-std=c++20", "-I", include_flag, "-c", str(path)],
        }

    (tmp_path / "compile_commands.json").write_text(
        json.dumps([entry(src / "hello.cpp"), entry(third / "skip.cpp")]),
        encoding="utf-8",
    )


def test_build_documents_headers_and_skips_ignored(tmp_path: Path) -> None:
    _project(tmp_path)
    result = build(tmp_path, languages=["cpp"], jobs=1, force=True)
    assert not any("third-party" in error for error in result["errors"])
    cache = tmp_path / ".cache" / "markdown-serve" / "cpp"
    header = (cache / "include" / "hello.hpp.md").read_text(encoding="utf-8")
    assert "Adds two integers." in header
    assert "[docs/notes.md](../docs/notes.md)" in header
    assert "Counts items." in header
    assert "width" in header
    assert "secret" not in header
    orphan = (cache / "include" / "orphan.hpp.md").read_text(encoding="utf-8")
    assert "Orphan" in orphan
    assert 'data-kind="include_guard" title="include guard"></span>ORPHAN_HPP' in orphan
    assert 'data-kind="macro" title="macro"></span>ORPHAN_LIMIT' in orphan
    assert 'data-kind="struct" title="struct"></span>Orphan' in orphan
    source = (cache / "src" / "hello.cpp.md").read_text(encoding="utf-8")
    assert "Hidden helper." in source
    assert "helper" in source
    assert "[``](#symbol)" not in source
    assert not (cache / "third-party" / "skip.cpp.md").exists()
    index = (cache / "index.md").read_text(encoding="utf-8")
    assert "../../../include/hello.hpp" in index

    header_path = cache / "include" / "hello.hpp.md"
    first_mtime = header_path.stat().st_mtime_ns
    again = build(tmp_path, languages=["cpp"], jobs=1)
    assert again["errors"] == [] or all("cancelled" not in error for error in again["errors"])
    assert header_path.stat().st_mtime_ns == first_mtime
