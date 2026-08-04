"""Persistent viewer config (theme + Pygments styles)."""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from pygments.styles import get_all_styles

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
AVAILABLE_STYLES = sorted(get_all_styles())
_STYLE_SET = set(AVAILABLE_STYLES)

DEFAULT_CONFIG: dict[str, Any] = {
    "theme": "light",
    "styles": {
        "light": "default",
        "dark": "nord",
    },
}

_lock = threading.Lock()


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    cfg = deepcopy(DEFAULT_CONFIG)
    theme = data.get("theme", cfg["theme"])
    if theme not in {"light", "dark"}:
        theme = cfg["theme"]
    cfg["theme"] = theme

    styles = data.get("styles") or {}
    if not isinstance(styles, dict):
        styles = {}
    for mode in ("light", "dark"):
        name = styles.get(mode, cfg["styles"][mode])
        if name not in _STYLE_SET:
            name = cfg["styles"][mode]
        cfg["styles"][mode] = name
    return cfg


def load_config() -> dict[str, Any]:
    with _lock:
        if not CONFIG_PATH.is_file():
            save_config(DEFAULT_CONFIG)
            return deepcopy(DEFAULT_CONFIG)
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return deepcopy(DEFAULT_CONFIG)
        if not isinstance(raw, dict):
            return deepcopy(DEFAULT_CONFIG)
        return _normalize(raw)


def save_config(data: dict[str, Any]) -> dict[str, Any]:
    cfg = _normalize(data)
    with _lock:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return cfg


def update_config(patch: dict[str, Any]) -> dict[str, Any]:
    current = load_config()
    if "theme" in patch:
        current["theme"] = patch["theme"]
    if "styles" in patch and isinstance(patch["styles"], dict):
        current["styles"] = {**current["styles"], **patch["styles"]}
    return save_config(current)


def public_config() -> dict[str, Any]:
    cfg = load_config()
    return {
        **cfg,
        "available_styles": AVAILABLE_STYLES,
    }
