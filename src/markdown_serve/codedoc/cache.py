"""Cache layout under ``<root>/<cache_dir>/`` and the manifest used for incremental builds."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from markdown_serve.project_config import load_project_config

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 2


def cache_dir(root: Path, cfg: dict | None = None) -> Path:
    config = cfg if cfg is not None else load_project_config(root)
    return root / config["codedoc"]["cache_dir"]


def page_path(cache: Path, language: str, rel_source: str) -> Path:
    return cache / language / f"{rel_source}.md"


def index_rel(cfg: dict, language: str) -> str:
    return f"{cfg['codedoc']['cache_dir']}/{language}/index.md"


def find_doc_page(root: Path, rel_source: str) -> Path | None:
    cfg = load_project_config(root)
    cache = cache_dir(root, cfg)
    for language in cfg["codedoc"]["languages"]:
        path = page_path(cache, language, rel_source)
        if path.is_file():
            return path
    return None


def load_manifest(cache: Path) -> dict[str, Any]:
    path = cache / MANIFEST_NAME
    if not path.is_file():
        return _empty_manifest()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_manifest()
    if not isinstance(raw, dict) or raw.get("version") != MANIFEST_VERSION:
        return _empty_manifest()
    raw.setdefault("languages", {})
    return raw


def save_manifest(cache: Path, manifest: dict[str, Any]) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    manifest["version"] = MANIFEST_VERSION
    manifest["built_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (cache / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def empty_language() -> dict[str, Any]:
    return {"files": {}, "units": {}, "tools": {}}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def unit_fingerprint(source: Path, args: tuple[str, ...] | list[str]) -> str:
    digest = hashlib.sha256()
    digest.update(source.read_bytes())
    digest.update(b"\0")
    digest.update("\0".join(args).encode())
    return digest.hexdigest()


def unit_key(rel: str, args: tuple[str, ...] | list[str]) -> str:
    flags = hashlib.sha256("\0".join(args).encode()).hexdigest()[:12]
    return f"{rel}@{flags}"


def select_stale_units(
    units: list[tuple[str, str, tuple[str, ...]]],
    manifest_lang: dict[str, Any],
    file_sha: dict[str, str],
    *,
    force: bool,
) -> tuple[list[int], list[int]]:
    """Split unit indexes into ``(stale, skipped)``.

    ``units`` entries are ``(key, rel, fingerprint)``. A skipped unit is reused only when
    its fingerprint matches and every source file it produced still has the same hash.
    """
    previous = manifest_lang.get("units") or {}
    files = manifest_lang.get("files") or {}
    stale: list[int] = []
    skipped: list[int] = []
    for index, (key, _rel, fingerprint) in enumerate(units):
        stored = previous.get(key)
        if force or not isinstance(stored, dict) or stored.get("hash") != fingerprint:
            stale.append(index)
            continue
        produced = stored.get("files") or []
        changed = False
        for rel in produced:
            current = file_sha.get(rel)
            old = (files.get(rel) or {}).get("sha256")
            if current is None or current != old:
                changed = True
                break
        if changed:
            stale.append(index)
        else:
            skipped.append(index)
    return stale, skipped


def manifest_summary(manifest: dict[str, Any]) -> dict[str, Any] | None:
    if not manifest.get("built_at") and not manifest.get("languages"):
        return None
    languages = {}
    for name, payload in (manifest.get("languages") or {}).items():
        files = payload.get("files") or {}
        languages[name] = {
            "files": len(files),
            "symbols": sum(int((info or {}).get("symbols") or 0) for info in files.values()),
        }
    return {"built_at": manifest.get("built_at"), "languages": languages}


def _empty_manifest() -> dict[str, Any]:
    return {"version": MANIFEST_VERSION, "built_at": None, "languages": {}}
