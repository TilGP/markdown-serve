"""Per-project .markdown-serve.json and ignore globs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from markdown_serve import main
from markdown_serve.codedoc.registry import active_languages, tools_status
from markdown_serve.project_config import (
    DEFAULT_PROJECT_CONFIG,
    PROJECT_CONFIG_NAME,
    PROJECT_CONFIG_SCHEMA,
    default_project_config_template,
    load_project_config,
    make_ignore,
    write_project_config,
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


def test_write_creates_defaults_without_internal_keys(tmp_path: Path) -> None:
    path, added, created = write_project_config(tmp_path)
    assert created
    assert path == tmp_path / PROJECT_CONFIG_NAME
    assert added == ["$schema", "ignore", "codedoc"]
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written == default_project_config_template()
    assert "languages_explicit" not in written["codedoc"]
    assert written["ignore"] == DEFAULT_PROJECT_CONFIG["ignore"]
    assert written["codedoc"]["cpp"] == DEFAULT_PROJECT_CONFIG["codedoc"]["cpp"]
    assert path.read_text(encoding="utf-8").endswith("}\n")


def test_write_fills_missing_keys_and_keeps_existing(tmp_path: Path) -> None:
    path = tmp_path / PROJECT_CONFIG_NAME
    path.write_text(
        '{"ignore": ["vendor/**"], "codedoc": {"jobs": 2, "cpp": {"libclang": "/opt/x.so"}}, "extra": 1}\n',
        encoding="utf-8",
    )
    _, added, created = write_project_config(tmp_path)
    assert not created
    assert added == ["$schema", "codedoc.cache_dir", "codedoc.languages", "codedoc.cpp.compile_commands"]
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["ignore"] == ["vendor/**"]
    assert written["codedoc"]["jobs"] == 2
    assert written["codedoc"]["cpp"] == {"libclang": "/opt/x.so", "compile_commands": "compile_commands.json"}
    assert written["codedoc"]["cache_dir"] == ".cache/markdown-serve"
    assert written["codedoc"]["languages"] == ["cpp", "python"]
    assert written["extra"] == 1

    # Second run: nothing to add, file left untouched.
    before = path.read_text(encoding="utf-8")
    _, added, _ = write_project_config(tmp_path)
    assert added == []
    assert path.read_text(encoding="utf-8") == before


def test_write_refuses_to_clobber_bad_json(tmp_path: Path) -> None:
    path = tmp_path / PROJECT_CONFIG_NAME
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError):
        write_project_config(tmp_path)
    assert path.read_text(encoding="utf-8") == "{"

    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="expected a JSON object"):
        write_project_config(tmp_path)
    assert path.read_text(encoding="utf-8") == "[1, 2]"


def test_schema_documents_every_template_key() -> None:
    schema = json.loads(
        (Path(__file__).parents[1] / "markdown-serve.schema.json").read_text(encoding="utf-8")
    )
    assert schema["$id"] == PROJECT_CONFIG_SCHEMA

    def check(node: dict, props: dict) -> None:
        for key, value in node.items():
            assert key in props
            assert props[key].get("description")
            if isinstance(value, dict):
                check(value, props[key]["properties"])

    check(default_project_config_template(), schema["properties"])


def test_init_cli(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    def fail(_prompt: str = "") -> str:
        raise AssertionError("prompted")

    monkeypatch.setattr("builtins.input", fail)
    main(["init"])
    assert (tmp_path / PROJECT_CONFIG_NAME).is_file()
    assert "Wrote" in capsys.readouterr().out

    main(["init"])
    assert "already has every key" in capsys.readouterr().out

    other = tmp_path / "other"
    other.mkdir()
    original = '{"codedoc": {}}\n'
    (other / PROJECT_CONFIG_NAME).write_text(original, encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    main(["init", "--root", str(other)])
    declined = capsys.readouterr().out
    assert "Will add to" in declined
    assert '"ignore"' in declined
    assert ".cache/markdown-serve" in declined
    assert "unchanged" in declined
    assert (other / PROJECT_CONFIG_NAME).read_text(encoding="utf-8") == original

    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    main(["init", "--root", str(other)])
    out = capsys.readouterr().out
    assert "Updated" in out and "ignore" in out and "codedoc.cache_dir" in out
    assert json.loads((other / PROJECT_CONFIG_NAME).read_text(encoding="utf-8"))["ignore"]

    (other / PROJECT_CONFIG_NAME).write_text("{", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main(["init", "-r", str(other)])
    assert exc.value.code == 1
    assert "error:" in capsys.readouterr().err
