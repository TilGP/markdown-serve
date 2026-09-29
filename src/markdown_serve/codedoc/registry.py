"""Registered language backends. Add a language by registering it here."""

from __future__ import annotations

import os
from pathlib import Path

from markdown_serve.codedoc.base import ToolStatus
from markdown_serve.codedoc.cpp.backend import CppBackend
from markdown_serve.codedoc.python.backend import PythonBackend
from markdown_serve.project_config import make_ignore

# Future: a "go" backend (go doc) registers beside these. One project can enable several.
BACKENDS = {"cpp": CppBackend(), "python": PythonBackend()}

# Same directories the server refuses to watch. Duplicated to avoid importing app.
_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".tox", ".mypy_cache", ".cache"}
_PRESENT: dict[tuple, list[str]] = {}


def backend_for(language: str):
    try:
        return BACKENDS[language]
    except KeyError as exc:
        known = ", ".join(sorted(BACKENDS)) or "none"
        raise KeyError(f"unknown language {language!r} (known: {known})") from exc


def code_suffixes() -> set[str]:
    suffixes: set[str] = set()
    for backend in BACKENDS.values():
        suffixes |= set(backend.suffixes)
    return suffixes


def active_languages(root: Path, cfg: dict) -> list[str]:
    """Languages to build and to list in the Code docs panel.

    An explicit ``codedoc.languages`` list is kept as written. The default list
    drops a language when the tree has no source file for it, so a Python
    project does not report a missing ``compile_commands.json``.
    """
    languages = [lang for lang in cfg["codedoc"]["languages"] if lang in BACKENDS]
    if cfg["codedoc"].get("languages_explicit"):
        return languages
    root = root.resolve()
    config_path = root / ".markdown-serve.json"
    try:
        stamp = config_path.stat().st_mtime_ns
    except OSError:
        stamp = 0
    key = (str(root), stamp, tuple(languages), tuple(cfg["ignore"]))
    cached = _PRESENT.get(key)
    if cached is not None:
        return list(cached)
    ignored = make_ignore(
        cfg["ignore"],
        cache_dir=cfg["codedoc"]["cache_dir"],
        skip_dirs=_SKIP_DIRS,
    )
    present = _languages_present(root, languages, ignored)
    _PRESENT[key] = present
    return list(present)


def check_language(root: Path, cfg: dict, language: str) -> ToolStatus:
    return backend_for(language).check(root, cfg)


def boot_status(root: Path, cfg: dict) -> dict:
    available = False
    for language in active_languages(root, cfg):
        if backend_for(language).check(root, cfg).available:
            available = True
            break
    return {"enabled": True, "available": available}


def tools_status(root: Path, cfg: dict) -> dict:
    payload = {}
    for language in active_languages(root, cfg):
        backend = BACKENDS.get(language)
        if backend is None:
            payload[language] = ToolStatus(
                False, [f"unknown language {language!r}"], [], []
            ).as_dict()
            continue
        payload[language] = backend.check(root, cfg).as_dict()
    return payload


def _languages_present(root: Path, languages: list[str], is_ignored) -> list[str]:
    wanted = {lang: set(BACKENDS[lang].suffixes) for lang in languages}
    found: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        try:
            rel_dir = Path(dirpath).resolve().relative_to(root).as_posix()
        except ValueError:
            dirnames[:] = []
            continue
        if rel_dir != "." and (is_ignored(rel_dir) or is_ignored(rel_dir + "/file")):
            dirnames[:] = []
            continue
        dirnames[:] = [name for name in dirnames if name not in _SKIP_DIRS and not name.startswith(".")]
        for name in filenames:
            suffix = Path(name).suffix.lower()
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            if is_ignored(rel):
                continue
            for language, suffixes in wanted.items():
                if suffix in suffixes:
                    found.add(language)
            if found >= set(wanted):
                return [lang for lang in languages if lang in found]
    return [lang for lang in languages if lang in found]
