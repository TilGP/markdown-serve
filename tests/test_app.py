"""App routing tests for standalone diagram files (no HTTP client dependency)."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from starlette.requests import Request

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


def _request(method: str, path: str, body: bytes = b"", accept: str = "") -> Request:
    headers = []
    if accept:
        headers.append((b"accept", accept.encode()))
    if body:
        headers.append((b"content-type", b"application/json"))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 123),
        "server": ("127.0.0.1", 80),
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


def test_code_file_without_cache_renders_source(workspace: Path) -> None:
    (workspace / "foo.hpp").write_text("int value;\n", encoding="utf-8")
    app = create_app(workspace)
    render = _endpoint(app, "/__api/render/{file_path:path}")
    data = _run(render("foo.hpp"))
    assert data["path"] == "foo.hpp"
    assert "No documentation cache" in data["html"]
    assert "int" in data["html"]
    assert data["text"] == "int value;\n"
    files = _run(_endpoint(app, "/__api/files")())
    assert "foo.hpp" not in files


def test_code_file_render_uses_cache_and_keeps_source_path(workspace: Path) -> None:
    (workspace / "foo.hpp").write_text("int value;\n", encoding="utf-8")
    cached = workspace / ".cache" / "markdown-serve" / "cpp" / "foo.hpp.md"
    cached.parent.mkdir(parents=True)
    cached.write_text(
        "\n".join(
            [
                '<a id="value"></a>',
                "## value",
                "",
                "```cppdoc",
                "int value",
                "```",
                "",
                "Defined at [foo.hpp:1](foo.hpp?line=1).",
                "",
                "See [notes](notes.md).",
                "",
            ]
        ),
        encoding="utf-8",
    )
    app = create_app(workspace)
    render = _endpoint(app, "/__api/render/{file_path:path}")
    data = _run(render("foo.hpp"))
    assert data["path"] == "foo.hpp"
    assert "notes.md" in data["html"]
    assert ".cache/" not in data["path"]
    files = _run(_endpoint(app, "/__api/files")())
    assert all(not name.startswith(".cache") for name in files)


def test_code_path_serves_the_viewer_shell(workspace: Path) -> None:
    (workspace / "foo.hpp").write_text("int value;\n", encoding="utf-8")
    app = create_app(workspace)
    serve = _endpoint(app, "/{file_path:path}")
    response = _run(serve("foo.hpp", _request("GET", "/foo.hpp", accept="text/html")))
    body = response.body.decode()
    assert "markdown-serve-boot" in body
    assert "foo.hpp" in body


def test_codedoc_status_and_files(workspace: Path) -> None:
    app = create_app(workspace)
    status = _run(_endpoint(app, "/__api/codedoc/status")())
    assert status["running"] is False
    assert "cpp" in status["tools"]
    assert "ignore" in status["config"]
    cache = workspace / ".cache" / "markdown-serve"
    cache.mkdir(parents=True)
    (cache / "manifest.json").write_text(
        '{"version":2,"built_at":"2026-01-01T00:00:00Z","languages":{"cpp":{"files":{"foo.hpp":{"sha256":"a","symbols":1}},"units":{},"tools":{}}}}\n',
        encoding="utf-8",
    )
    listed = _run(_endpoint(app, "/__api/codedoc/files")())
    assert listed == ["foo.hpp"]


def test_codedoc_build_conflicts_when_already_running(workspace: Path) -> None:
    app = create_app(workspace)
    app.state.codedoc_job.running = True
    build = _endpoint(app, "/__api/codedoc/build")
    with pytest.raises(HTTPException) as exc:
        _run(build(_request("POST", "/__api/codedoc/build", b"{}")))
    assert exc.value.status_code == 409


def test_search_includes_diagram_files(workspace: Path) -> None:
    app = create_app(workspace)
    search = _endpoint(app, "/__api/search")
    hits = _run(search(q="'flowchart"))
    assert [h["path"] for h in hits] == ["flow.mmd"]
