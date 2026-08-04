"""Live markdown preview server."""

from __future__ import annotations

import asyncio
import html
import json
import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from markdown_serve.plantuml import PlantUMLError, render_plantuml_svg
from markdown_serve.render import pygments_css, render_markdown

MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkd"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico", ".avif"}
PDF_SUFFIXES = {".pdf"}
SIDEBAR_SUFFIXES = MARKDOWN_SUFFIXES | IMAGE_SUFFIXES | PDF_SUFFIXES
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".tox", ".mypy_cache"}


def _wants_document(accept: str) -> bool:
    """True for browser navigations; False for <img>/asset fetches."""
    if not accept:
        return True
    for part in accept.split(","):
        mime = part.split(";")[0].strip().lower()
        if mime == "text/html":
            return True
        if mime.startswith("image/") or mime in {"application/pdf", "application/octet-stream"}:
            return False
    return "text/html" in accept.lower()


class _ReloadHandler(FileSystemEventHandler):
    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[str]) -> None:
        super().__init__()
        self._loop = loop
        self._queue = queue

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        src = event.src_path
        if isinstance(src, bytes):
            src = src.decode()
        path = Path(src)
        if any(part in SKIP_DIRS for part in path.parts):
            return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, path.as_posix())


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    async def broadcast(self, message: str) -> None:
        dead: list[WebSocket] = []
        for client in self._clients:
            try:
                await client.send_text(message)
            except Exception:
                dead.append(client)
        for client in dead:
            self._clients.discard(client)


def create_app(root: Path) -> FastAPI:
    root = root.resolve()
    manager = ConnectionManager()
    event_queue: asyncio.Queue[str] = asyncio.Queue()
    observer = Observer()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        loop = asyncio.get_running_loop()
        handler = _ReloadHandler(loop, event_queue)
        observer.schedule(handler, str(root), recursive=True)
        observer.start()

        async def broadcaster() -> None:
            while True:
                path = await event_queue.get()
                # Debounce bursts of filesystem events
                await asyncio.sleep(0.15)
                while not event_queue.empty():
                    path = event_queue.get_nowait()
                try:
                    rel = Path(path).resolve().relative_to(root).as_posix()
                except ValueError:
                    rel = path
                await manager.broadcast(rel)

        task = asyncio.create_task(broadcaster())
        try:
            yield
        finally:
            task.cancel()
            observer.stop()
            observer.join(timeout=2)

    app = FastAPI(title="markdown-serve", lifespan=lifespan)
    app.state.root = root
    app.state.manager = manager

    def resolve_under_root(rel: str) -> Path:
        # Strip leading slashes; treat as path relative to root
        candidate = (root / rel.lstrip("/")).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="Forbidden") from exc
        return candidate

    def list_sidebar_files() -> list[str]:
        files: list[str] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SIDEBAR_SUFFIXES:
                continue
            if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
                continue
            files.append(path.relative_to(root).as_posix())
        return files

    @app.websocket("/__ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    @app.get("/__api/files")
    async def api_files() -> list[str]:
        return list_sidebar_files()

    @app.get("/__api/render/{file_path:path}")
    async def api_render(file_path: str) -> dict[str, str]:
        path = resolve_under_root(file_path)
        if not path.is_file() or path.suffix.lower() not in MARKDOWN_SUFFIXES:
            raise HTTPException(status_code=404, detail="Markdown file not found")
        text = path.read_text(encoding="utf-8")
        return {"path": file_path, "html": render_markdown(text)}

    @app.post("/__api/plantuml")
    async def api_plantuml(request: Request) -> Response:
        source = (await request.body()).decode("utf-8", errors="replace")
        try:
            svg = render_plantuml_svg(source)
        except PlantUMLError as exc:
            return Response(content=str(exc), status_code=400, media_type="text/plain; charset=utf-8")
        return Response(content=svg, media_type="image/svg+xml; charset=utf-8")

    @app.get("/__file/{file_path:path}")
    async def serve_raw_file(file_path: str) -> Response:
        path = resolve_under_root(file_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Not found")
        media_type, _ = mimetypes.guess_type(str(path))
        return Response(content=path.read_bytes(), media_type=media_type or "application/octet-stream")

    @app.get("/__assets/pygments.css")
    async def pygments_stylesheet() -> Response:
        return Response(content=pygments_css(), media_type="text/css; charset=utf-8")

    @app.get("/__assets/{asset_path:path}")
    async def serve_ui_asset(asset_path: str) -> Response:
        return ui_asset_response(asset_path)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        files = list_sidebar_files()
        md_files = [f for f in files if Path(f).suffix.lower() in MARKDOWN_SUFFIXES]
        preferred = next(
            (f for f in ("README.md", "readme.md", "index.md", "INDEX.md") if f in md_files),
            md_files[0] if md_files else (files[0] if files else None),
        )
        return page_shell(root.name, preferred or "", files)

    @app.get("/{file_path:path}")
    async def serve_path(file_path: str, request: Request) -> Response:
        path = resolve_under_root(file_path)

        if path.is_dir():
            rel = path.relative_to(root).as_posix()
            prefix = "" if rel == "." else rel + "/"
            files = list_sidebar_files()
            under = [f for f in files if f.startswith(prefix) or rel == "."]
            preferred = under[0] if under else ""
            return HTMLResponse(page_shell(root.name, preferred, files))

        if not path.is_file():
            raise HTTPException(status_code=404, detail="Not found")

        suffix = path.suffix.lower()
        accept = request.headers.get("accept", "")
        if suffix in SIDEBAR_SUFFIXES and _wants_document(accept):
            files = list_sidebar_files()
            rel = path.relative_to(root).as_posix()
            return HTMLResponse(page_shell(root.name, rel, files))

        # Linked assets (markdown images, css, fonts, etc.)
        media_type, _ = mimetypes.guess_type(str(path))
        return Response(content=path.read_bytes(), media_type=media_type or "application/octet-stream")

    return app



ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_INDEX_TEMPLATE = (ASSETS_DIR / "index.html").read_text(encoding="utf-8")
_UI_ASSET_SUFFIXES = {".js", ".css", ".mjs", ".map", ".woff", ".woff2", ".ttf", ".otf"}


def ui_asset_response(asset_path: str) -> Response:
    """Serve packaged UI files (css/js/fonts). Reject jars and path escapes."""
    candidate = (ASSETS_DIR / asset_path).resolve()
    try:
        candidate.relative_to(ASSETS_DIR)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Forbidden") from exc
    if not candidate.is_file() or candidate.name == "index.html":
        raise HTTPException(status_code=404, detail="Not found")
    if candidate.suffix.lower() not in _UI_ASSET_SUFFIXES:
        raise HTTPException(status_code=404, detail="Not found")
    media_type, _ = mimetypes.guess_type(str(candidate))
    return Response(
        content=candidate.read_bytes(),
        media_type=media_type or "application/octet-stream",
        headers={"Cache-Control": "no-cache"},
    )


def page_shell(title: str, active: str, files: list[str]) -> str:
    boot = json.dumps(
        {"initialPath": active, "files": files},
        ensure_ascii=False,
    ).replace("<", "\\u003c")
    return (
        _INDEX_TEMPLATE
        .replace("__TITLE__", html.escape(title))
        .replace("__BOOT_JSON__", boot)
    )
