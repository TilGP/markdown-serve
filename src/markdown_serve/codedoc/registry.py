"""Registered language backends. Add a language by registering it here."""

from __future__ import annotations

from pathlib import Path

from markdown_serve.codedoc.base import ToolStatus
from markdown_serve.codedoc.cpp.backend import CppBackend

# Future: a "go" backend (go doc) registers beside cpp. One project can enable several.
BACKENDS = {"cpp": CppBackend()}


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


def check_language(root: Path, cfg: dict, language: str) -> ToolStatus:
    return backend_for(language).check(root, cfg)


def boot_status(root: Path, cfg: dict) -> dict:
    available = False
    for language in cfg["codedoc"]["languages"]:
        backend = BACKENDS.get(language)
        if backend is not None and backend.check(root, cfg).available:
            available = True
            break
    return {"enabled": True, "available": available}


def tools_status(root: Path, cfg: dict) -> dict:
    payload = {}
    for language in cfg["codedoc"]["languages"]:
        backend = BACKENDS.get(language)
        if backend is None:
            payload[language] = ToolStatus(
                False, [f"unknown language {language!r}"], [], []
            ).as_dict()
            continue
        payload[language] = backend.check(root, cfg).as_dict()
    return payload
