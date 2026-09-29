"""Per-project settings from ``<root>/.markdown-serve.json``."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable, Iterable
from copy import deepcopy
from pathlib import Path
from typing import Any

PROJECT_CONFIG_NAME = ".markdown-serve.json"
PROJECT_CONFIG_SCHEMA = (
    "https://raw.githubusercontent.com/TilGP/markdown-serve/main/markdown-serve.schema.json"
)

DEFAULT_PROJECT_CONFIG: dict[str, Any] = {
    "ignore": ["third-party/**", "cmake-build-*/**"],
    "codedoc": {
        "cache_dir": ".cache/markdown-serve",
        "languages": ["cpp", "python"],
        "jobs": None,
        "languages_explicit": False,
        "cpp": {
            "compile_commands": "compile_commands.json",
            "libclang": None,
        },
    },
}

# Set by the loader, never read from the file. Left out of ``init`` dumps.
_INTERNAL_KEYS: frozenset[tuple[str, ...]] = frozenset({("codedoc", "languages_explicit")})


def default_project_config_template() -> dict[str, Any]:
    """The defaults as a user would write them (internal keys removed)."""
    cfg = deepcopy(DEFAULT_PROJECT_CONFIG)
    for path in _INTERNAL_KEYS:
        node: Any = cfg
        for part in path[:-1]:
            node = node.get(part) if isinstance(node, dict) else None
        if isinstance(node, dict):
            node.pop(path[-1], None)
    return {"$schema": PROJECT_CONFIG_SCHEMA, **cfg}


def _plan(dst: dict[str, Any], defaults: dict[str, Any], prefix: str = "") -> tuple[list[str], dict[str, Any]]:
    """Keys from ``defaults`` that ``dst`` lacks, without changing ``dst``.

    Returns ``(dotted_names, additions)``. A missing object is one addition;
    a present object is walked so only its missing children are included.
    """
    added: list[str] = []
    extra: dict[str, Any] = {}
    for key, value in defaults.items():
        dotted = f"{prefix}{key}"
        if key not in dst:
            extra[key] = deepcopy(value)
            added.append(dotted)
        elif isinstance(value, dict) and isinstance(dst[key], dict):
            nested_added, nested_extra = _plan(dst[key], value, f"{dotted}.")
            added.extend(nested_added)
            if nested_extra:
                extra[key] = nested_extra
    return added, extra


def _apply(dst: dict[str, Any], additions: dict[str, Any]) -> None:
    for key, value in additions.items():
        if key in dst and isinstance(value, dict) and isinstance(dst[key], dict):
            _apply(dst[key], value)
        else:
            dst[key] = deepcopy(value)


def _read_project_config_file(root: Path) -> tuple[Path, dict[str, Any], bool]:
    """Return ``(path, object, created)``. A missing file is an empty object.

    Raises ``ValueError`` when the file exists but is not a JSON object.
    """
    path = root / PROJECT_CONFIG_NAME
    if not path.is_file():
        return path, {}, True
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return path, raw, False


def pending_project_config(root: Path) -> tuple[Path, list[str], dict[str, Any], bool]:
    """What ``write_project_config`` would add. Does not write.

    Returns ``(path, added_keys, additions, created)``.
    """
    path, raw, created = _read_project_config_file(root)
    added, additions = _plan(raw, default_project_config_template())
    return path, added, additions, created


def write_project_config(root: Path) -> tuple[Path, list[str], bool]:
    """Create ``.markdown-serve.json`` or add missing keys to an existing one.

    Returns ``(path, added_keys, created)``. Existing values and unknown keys
    are kept. Raises ``ValueError`` when the file exists but is not a JSON
    object, so user content is never overwritten.
    """
    path, added, additions, created = pending_project_config(root)
    if not additions:
        return path, added, created
    _, raw, _ = _read_project_config_file(root)
    _apply(raw, additions)
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return path, added, created


def _glob_to_regex(pattern: str) -> str:
    """Translate a path glob (``*`` in one segment, ``**`` across segments) to regex."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            i += 2
            if i < len(pattern) and pattern[i] == "/":
                i += 1
                # ``**/`` matches zero or more segments, including none.
                out.append("(?:.*/)?")
            else:
                out.append(".*")
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return "".join(out)


def make_ignore(
    patterns: Iterable[str],
    *,
    cache_dir: str = "",
    skip_dirs: Iterable[str] = (),
) -> Callable[[str], bool]:
    """Return a predicate on root-relative posix paths.

    ``re:`` prefixes a raw regex (searched, not anchored). Other entries are globs.
    ``cache_dir`` and any path segment in ``skip_dirs`` are always ignored.
    """
    globs: list[re.Pattern[str]] = []
    raws: list[re.Pattern[str]] = []
    for pattern in patterns:
        if pattern.startswith("re:"):
            try:
                raws.append(re.compile(pattern[3:]))
            except re.error as exc:
                print(f"warning: ignore regex {pattern!r}: {exc}", file=sys.stderr)
            continue
        globs.append(re.compile(r"\A" + _glob_to_regex(pattern) + r"\Z"))
    cache = cache_dir.strip("/")
    skipped = set(skip_dirs)

    def is_ignored(rel: str) -> bool:
        rel = rel.replace("\\", "/").lstrip("/")
        while rel.startswith("./"):
            rel = rel[2:]
        if not rel or rel == ".":
            return False
        if any(part in skipped for part in rel.split("/")):
            return True
        if cache and (rel == cache or rel.startswith(cache + "/")):
            return True
        if any(expr.fullmatch(rel) for expr in globs):
            return True
        return any(expr.search(rel) for expr in raws)

    return is_ignored


def _merge_cpp(dst: dict[str, Any], raw: Any) -> None:
    if not isinstance(raw, dict):
        return
    commands = raw.get("compile_commands")
    if isinstance(commands, str) and commands.strip():
        dst["compile_commands"] = commands.strip()
    if "libclang" in raw:
        lib = raw.get("libclang")
        dst["libclang"] = lib if isinstance(lib, str) and lib.strip() else None


def load_project_config(root: Path) -> dict[str, Any]:
    """Load ``.markdown-serve.json``. Unknown keys are ignored; bad JSON falls back."""
    cfg = deepcopy(DEFAULT_PROJECT_CONFIG)
    path = root / PROJECT_CONFIG_NAME
    if not path.is_file():
        return cfg
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"warning: {path}: {exc}; using defaults", file=sys.stderr)
        return cfg
    if not isinstance(raw, dict):
        print(f"warning: {path}: expected an object; using defaults", file=sys.stderr)
        return cfg
    ignore = raw.get("ignore")
    if isinstance(ignore, list):
        cfg["ignore"] = [str(item) for item in ignore if str(item).strip()]
    codedoc = raw.get("codedoc")
    if not isinstance(codedoc, dict):
        return cfg
    cache_dir = codedoc.get("cache_dir")
    if isinstance(cache_dir, str) and cache_dir.strip():
        cfg["codedoc"]["cache_dir"] = cache_dir.strip().strip("/")
    languages = codedoc.get("languages")
    if isinstance(languages, list) and languages:
        cfg["codedoc"]["languages"] = [str(item) for item in languages if str(item).strip()]
        cfg["codedoc"]["languages_explicit"] = True
    if "jobs" in codedoc:
        jobs = codedoc.get("jobs")
        if jobs is None:
            cfg["codedoc"]["jobs"] = None
        elif isinstance(jobs, int) and jobs > 0:
            cfg["codedoc"]["jobs"] = jobs
        else:
            print(f"warning: {path}: codedoc.jobs must be a positive integer or null", file=sys.stderr)
    _merge_cpp(cfg["codedoc"]["cpp"], codedoc.get("cpp"))
    return cfg
