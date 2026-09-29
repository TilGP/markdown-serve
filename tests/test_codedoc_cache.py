"""Cache manifest and incremental unit selection."""

from __future__ import annotations

from pathlib import Path

from markdown_serve.codedoc.cache import (
    find_doc_page,
    load_manifest,
    page_path,
    save_manifest,
    select_stale_units,
    unit_fingerprint,
)
from markdown_serve.codedoc.cpp.compile_commands import compiler_and_args, load_units
from markdown_serve.project_config import make_ignore


def test_manifest_roundtrip_and_lookup(tmp_path: Path) -> None:
    cache = tmp_path / ".cache" / "markdown-serve"
    page = page_path(cache, "cpp", "libs/foo.hpp")
    page.parent.mkdir(parents=True)
    page.write_text("# foo\n", encoding="utf-8")
    save_manifest(
        cache,
        {
            "languages": {
                "cpp": {
                    "files": {"libs/foo.hpp": {"sha256": "abc", "symbols": 2}},
                    "units": {},
                    "tools": {},
                }
            }
        },
    )
    manifest = load_manifest(cache)
    assert manifest["built_at"]
    assert manifest["languages"]["cpp"]["files"]["libs/foo.hpp"]["symbols"] == 2
    assert find_doc_page(tmp_path, "libs/foo.hpp") == page
    assert find_doc_page(tmp_path, "missing.hpp") is None


def test_select_stale_units_skips_unchanged_inputs(tmp_path: Path) -> None:
    source = tmp_path / "a.cpp"
    source.write_text("int a;\n", encoding="utf-8")
    header = tmp_path / "a.hpp"
    header.write_text("int a();\n", encoding="utf-8")
    fingerprint = unit_fingerprint(source, ["-std=c++20"])
    units = [("a.cpp@flags", "a.cpp", fingerprint)]
    manifest = {
        "units": {"a.cpp@flags": {"hash": fingerprint, "files": ["a.cpp", "a.hpp"]}},
        "files": {
            "a.cpp": {"sha256": __import__("hashlib").sha256(b"int a;\n").hexdigest(), "symbols": 1},
            "a.hpp": {"sha256": __import__("hashlib").sha256(b"int a();\n").hexdigest(), "symbols": 1},
        },
    }
    from markdown_serve.codedoc.cache import sha256_file

    file_sha = {"a.cpp": sha256_file(source), "a.hpp": sha256_file(header)}
    stale, skipped = select_stale_units(units, manifest, file_sha, force=False)
    assert stale == []
    assert skipped == [0]

    header.write_text("int b();\n", encoding="utf-8")
    file_sha["a.hpp"] = sha256_file(header)
    stale, skipped = select_stale_units(units, manifest, file_sha, force=False)
    assert stale == [0]
    assert skipped == []

    stale, skipped = select_stale_units(units, manifest, file_sha, force=True)
    assert stale == [0]


def test_compile_commands_drops_output_flags_and_ignored_files(tmp_path: Path) -> None:
    src = tmp_path / "src" / "a.cpp"
    src.parent.mkdir()
    src.write_text("int a;\n", encoding="utf-8")
    third = tmp_path / "third-party" / "b.cpp"
    third.parent.mkdir()
    third.write_text("int b;\n", encoding="utf-8")
    commands = tmp_path / "compile_commands.json"

    def entry(path: Path) -> dict:
        return {
            "directory": str(tmp_path),
            "file": str(path),
            "command": f"clang++ -c -std=c++20 -MD -MF {path}.d -o {path}.o {path}",
        }

    commands.write_text(__import__("json").dumps([entry(src), entry(third)]), encoding="utf-8")
    ignored = make_ignore(["third-party/**"], cache_dir=".cache/markdown-serve", skip_dirs=[".git"])
    units = load_units(tmp_path, commands, ignored)
    assert [unit.rel for unit in units] == ["src/a.cpp"]
    assert "-c" not in units[0].args
    assert "-o" not in units[0].args
    assert "-MD" not in units[0].args
    assert "-std=c++20" in units[0].args
    assert not any(arg.endswith("a.cpp") for arg in units[0].args)

    compiler, args = compiler_and_args(
        ["clang++", "-c", "-o", "out.o", str(src)],
        src.resolve(),
        tmp_path,
    )
    assert compiler == "clang++"
    assert args == []
