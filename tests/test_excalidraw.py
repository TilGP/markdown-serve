"""Excalidraw source → SVG."""

from __future__ import annotations

import json

import pytest

from markdown_serve.excalidraw import ExcalidrawError, render_excalidraw_svg

SCENE = {
    "type": "excalidraw",
    "version": 2,
    "appState": {"viewBackgroundColor": "#fffbe6"},
    "elements": [
        {
            "id": "r1",
            "type": "rectangle",
            "x": 10,
            "y": 10,
            "width": 80,
            "height": 40,
            "strokeColor": "#1e1e1e",
            "backgroundColor": "#a5d8ff",
            "fillStyle": "solid",
        },
        {
            "id": "t1",
            "type": "text",
            "x": 20,
            "y": 18,
            "width": 60,
            "height": 24,
            "text": "Hello",
            "fontSize": 20,
            "fontFamily": 1,
        },
    ],
}


def test_render_excalidraw_svg() -> None:
    svg = render_excalidraw_svg(json.dumps(SCENE))
    assert svg.startswith("<svg")
    assert 'fill="#fffbe6"' in svg
    assert ">Hello</text>" in svg


@pytest.mark.parametrize("source", ["", "   ", "not json", "[]"])
def test_render_excalidraw_rejects_bad_source(source: str) -> None:
    with pytest.raises(ExcalidrawError):
        render_excalidraw_svg(source)
