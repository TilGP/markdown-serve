"""App routing tests for standalone diagram files (no HTTP client dependency)."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from markdown_serve.app import create_app


def _endpoint(app: Any, path: str):
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == path:
            return route.endpoint
    raise AssertionError(f"route not found: {path}")


def _run(coro: Any) -> Any:
    """Run a coroutine even if Playwright left an event loop on this thread."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# Hi\n", encoding="utf-8")
    (tmp_path / "flow.mmd").write_text("flowchart LR\n  A --> B\n", encoding="utf-8")
    (tmp_path / "seq.puml").write_text("@startuml\nA -> B\n@enduml\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignored\n", encoding="utf-8")
    return tmp_path


def test_diagram_files_listed_in_sidebar(workspace: Path) -> None:
    app = create_app(workspace)
    files = _run(_endpoint(app, "/__api/files")())
    assert files == ["README.md", "flow.mmd", "seq.puml"]


@pytest.mark.parametrize(
    ("name", "kind"),
    [("flow.mmd", "mermaid"), ("seq.puml", "plantuml")],
)
def test_render_endpoint_wraps_diagram_files(workspace: Path, name: str, kind: str) -> None:
    app = create_app(workspace)
    render = _endpoint(app, "/__api/render/{file_path:path}")
    data = _run(render(name))
    assert data["path"] == name
    assert data["html"].startswith(f'<div class="diagram diagram-{kind}">')
    assert '<pre class="diagram-source">' in data["html"]
    assert data["text"] == (workspace / name).read_text(encoding="utf-8")


def test_render_endpoint_still_renders_markdown(workspace: Path) -> None:
    app = create_app(workspace)
    render = _endpoint(app, "/__api/render/{file_path:path}")
    data = _run(render("README.md"))
    assert "<h1" in data["html"]
    assert "diagram-source" not in data["html"]


def test_render_endpoint_rejects_non_text_files(workspace: Path) -> None:
    app = create_app(workspace)
    render = _endpoint(app, "/__api/render/{file_path:path}")
    with pytest.raises(HTTPException) as exc:
        _run(render("notes.txt"))
    assert exc.value.status_code == 404


def test_search_includes_diagram_files(workspace: Path) -> None:
    app = create_app(workspace)
    search = _endpoint(app, "/__api/search")
    hits = _run(search(q="'flowchart"))
    assert [h["path"] for h in hits] == ["flow.mmd"]
