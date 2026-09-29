"""Per-project .markdown-serve.json and ignore globs."""

from __future__ import annotations

from pathlib import Path

from markdown_serve.codedoc.registry import active_languages, tools_status
from markdown_serve.project_config import (
    DEFAULT_PROJECT_CONFIG,
    load_project_config,
    make_ignore,
)


def test_missing_file_uses_defaults(tmp_path: Path) -> None:
    cfg = load_project_config(tmp_path)
    assert cfg["ignore"] == ["third-party/**", "cmake-build-*/**"]
    assert cfg["codedoc"]["cache_dir"] == ".cache/markdown-serve"
    assert cfg["codedoc"]["languages"] == ["cpp", "python"]
    assert cfg["codedoc"]["jobs"] is None
    assert cfg["codedoc"]["cpp"]["compile_commands"] == "compile_commands.json"


def test_ignore_globs_regex_cache_and_skip_dirs(tmp_path: Path) -> None:
    ignored = make_ignore(
        ["third-party/**", "cmake-build-*/**", "re:^secret/"],
        cache_dir=".cache/markdown-serve",
        skip_dirs={".git"},
    )
    assert ignored("third-party/base64/base64.cpp")
    assert ignored("cmake-build-debug/CMakeFiles/x.cpp")
    assert not ignored("libs/ngn/src/rules.hpp")
    assert ignored("secret/key.hpp")
    assert ignored(".cache/markdown-serve/cpp/index.md")
    assert ignored(".git/config")
    assert not ignored("README.md")


def test_load_overrides_and_bad_json(tmp_path: Path, capsys) -> None:
    path = tmp_path / ".markdown-serve.json"
    path.write_text(
        '{"ignore": ["vendor/**"], "codedoc": {"jobs": 2, "cpp": {"libclang": "/opt/libclang.so"}}, "extra": 1}\n',
        encoding="utf-8",
    )
    cfg = load_project_config(tmp_path)
    assert cfg["ignore"] == ["vendor/**"]
    assert cfg["codedoc"]["jobs"] == 2
    assert cfg["codedoc"]["cpp"]["libclang"] == "/opt/libclang.so"
    assert cfg["codedoc"]["cache_dir"] == DEFAULT_PROJECT_CONFIG["codedoc"]["cache_dir"]
    assert "extra" not in cfg

    path.write_text("{", encoding="utf-8")
    fallback = load_project_config(tmp_path)
    assert fallback["ignore"] == DEFAULT_PROJECT_CONFIG["ignore"]
    assert "using defaults" in capsys.readouterr().err


def test_default_languages_follow_the_files_in_the_tree(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    (tmp_path / "third-party").mkdir()
    (tmp_path / "third-party" / "vendored.cpp").write_text("int x;\n", encoding="utf-8")
    cfg = load_project_config(tmp_path)
    assert active_languages(tmp_path, cfg) == ["python"]
    tools = tools_status(tmp_path, cfg)
    assert list(tools) == ["python"]
    assert "compile_commands.json" not in str(tools)

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
    # The file scan is cached until the config file changes.
    from markdown_serve.codedoc import registry

    registry._PRESENT.clear()
    assert active_languages(tmp_path, cfg) == ["cpp", "python"]

    (tmp_path / ".markdown-serve.json").write_text(
        '{"codedoc": {"languages": ["cpp"]}}\n',
        encoding="utf-8",
    )
    forced = load_project_config(tmp_path)
    assert active_languages(tmp_path, forced) == ["cpp"]
