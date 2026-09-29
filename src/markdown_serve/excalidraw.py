"""Excalidraw rendering via excalidraw-render (no browser)."""

from __future__ import annotations

import json

from excalidraw_render.element import parse_scene
from excalidraw_render.render import render_svg


class ExcalidrawError(RuntimeError):
    pass


def render_excalidraw_svg(source: str) -> str:
    text = source.strip()
    if not text:
        raise ExcalidrawError("Empty Excalidraw source")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExcalidrawError(f"Invalid Excalidraw JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ExcalidrawError("Excalidraw source must be a JSON object")

    background = "#ffffff"
    app_state = data.get("appState")
    if isinstance(app_state, dict):
        color = app_state.get("viewBackgroundColor")
        if isinstance(color, str) and color.strip():
            background = color

    try:
        svg = render_svg(parse_scene(data), background=background)
    except Exception as exc:
        raise ExcalidrawError(str(exc) or "Excalidraw render failed") from exc

    if "<svg" not in svg.lower():
        raise ExcalidrawError("Excalidraw did not return SVG")
    return svg
