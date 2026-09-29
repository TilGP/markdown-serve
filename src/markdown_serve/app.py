"""Live markdown preview server."""

from __future__ import annotations

import asyncio
import html
import json
import mimetypes
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from watchdog.events import (
    EVENT_TYPE_CLOSED_NO_WRITE,
    EVENT_TYPE_OPENED,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from markdown_serve.codedoc.builder import build
from markdown_serve.codedoc.cache import find_doc_page, load_manifest, manifest_summary
from markdown_serve.codedoc.registry import active_languages, boot_status, code_suffixes, tools_status
from markdown_serve.codedoc.xrefs import load_symbol_index, render_codedoc_page
from markdown_serve.config import (
    font_stack_css,
    load_config,
    public_config,
    update_config,
    wrap_css_vars,
)
from markdown_serve.plantuml import PlantUMLError, render_plantuml_svg
from markdown_serve.project_config import load_project_config
from markdown_serve.render import pygments_css, render_diagram, render_markdown, render_source_code
from markdown_serve.search import search_markdown

MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkd"}
MERMAID_SUFFIXES = {".mmd", ".mermaid"}
PLANTUML_SUFFIXES = {".puml", ".plantuml", ".pu", ".iuml", ".wsd"}
DIAGRAM_SUFFIXES = MERMAID_SUFFIXES | PLANTUML_SUFFIXES
# Text files rendered via /__api/render (and covered by content search).
TEXT_SUFFIXES = MARKDOWN_SUFFIXES | DIAGRAM_SUFFIXES
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico", ".avif"}
PDF_SUFFIXES = {".pdf"}
CSV_SUFFIXES = {".csv", ".tsv"}
SIDEBAR_SUFFIXES = TEXT_SUFFIXES | IMAGE_SUFFIXES | PDF_SUFFIXES | CSV_SUFFIXES
CODE_SUFFIXES = code_suffixes()
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".tox", ".mypy_cache", ".cache"}
# inotify reports plain reads (our own render/search) as open/close events;
# rebroadcasting those would make the browser reload in a loop.
READ_ONLY_EVENT_TYPES = {EVENT_TYPE_OPENED, EVENT_TYPE_CLOSED_NO_WRITE}


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
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue[str],
        skip_rel,
    ) -> None:
        super().__init__()
        self._loop = loop
        self._queue = queue
        self._skip_rel = skip_rel

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory or event.event_type in READ_ONLY_EVENT_TYPES:
            return
        src = event.src_path
        if isinstance(src, bytes):
            src = src.decode()
        path = Path(src)
        if any(part in SKIP_DIRS for part in path.parts) or self._skip_rel(path):
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


class _CodeDocJob:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = False
        self.cancel = threading.Event()
        self.thread: threading.Thread | None = None
        self.progress: dict = {
            "phase": "idle",
            "done": 0,
            "total": 0,
            "current": "",
            "errors": [],
            "language": "",
        }


def create_app(root: Path) -> FastAPI:
    root = root.resolve()
    manager = ConnectionManager()
    event_queue: asyncio.Queue[str] = asyncio.Queue()
    observer = Observer()
    project_cfg = load_project_config(root)
    doc_cache = project_cfg["codedoc"]["cache_dir"]
    job = _CodeDocJob()

    def _skip_rel(path: Path) -> bool:
        try:
            rel = path.resolve().relative_to(root).as_posix()
        except (OSError, ValueError):
            return False
        return rel == doc_cache or rel.startswith(doc_cache + "/")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        loop = asyncio.get_running_loop()
        app.state.loop = loop
        handler = _ReloadHandler(loop, event_queue, _skip_rel)
        observer.schedule(handler, str(root), recursive=True)
        observer.start()

        async def broadcaster() -> None:
            while True:
                path = await event_queue.get()
                # Debounce bursts of filesystem events
                await asyncio.sleep(0.15)
                codedoc_done = Path(path).name == "__codedoc__"
                while not event_queue.empty():
                    path = event_queue.get_nowait()
                    codedoc_done = codedoc_done or Path(path).name == "__codedoc__"
                if codedoc_done:
                    await manager.broadcast("__codedoc__")
                if Path(path).name == "__codedoc__":
                    continue
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
    app.state.codedoc_job = job
    app.state.loop = None

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
            rel = path.relative_to(root).as_posix()
            if any(part in SKIP_DIRS for part in rel.split("/")):
                continue
            if rel == doc_cache or rel.startswith(doc_cache + "/"):
                continue
            files.append(rel)
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

    @app.get("/__api/search")
    async def api_search(q: str = "") -> list[dict]:
        query = q.strip()
        if not query:
            return []
        text_files = [
            f for f in list_sidebar_files() if Path(f).suffix.lower() in TEXT_SUFFIXES
        ]
        return search_markdown(root, text_files, query)

    @app.get("/__api/exists/{file_path:path}")
    async def api_exists(file_path: str) -> dict[str, bool | str]:
        path = resolve_under_root(file_path)
        return {"path": file_path, "exists": path.exists()}

    def _code_doc_html(rel: str, source_text: str) -> str:
        page = find_doc_page(root, rel)
        if page is None or not page.is_file():
            hint = (
                "> No documentation cache for this file. "
                "Build it from the Code docs panel.\n\n"
            )
            return render_markdown(hint) + render_source_code(source_text)
        built = datetime.fromtimestamp(page.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        banner = (
            f"> Generated code documentation for `{rel}`. "
            f"[View source](/__file/{rel}). Built {built}.\n\n"
        )
        return render_codedoc_page(banner + page.read_text(encoding="utf-8"), rel, load_symbol_index(root))

    @app.get("/__api/render/{file_path:path}")
    async def api_render(file_path: str) -> dict[str, str]:
        path = resolve_under_root(file_path)
        suffix = path.suffix.lower()
        if path.is_file() and suffix in CODE_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="replace")
            return {"path": file_path, "html": _code_doc_html(file_path, text), "text": text}
        if not path.is_file() or suffix not in TEXT_SUFFIXES:
            raise HTTPException(status_code=404, detail="Renderable file not found")
        text = path.read_text(encoding="utf-8")
        if suffix in MERMAID_SUFFIXES:
            rendered = render_diagram(text, "mermaid")
        elif suffix in PLANTUML_SUFFIXES:
            rendered = render_diagram(text, "plantuml")
        else:
            rendered = render_markdown(text)
        return {"path": file_path, "html": rendered, "text": text}

    def _codedoc_status() -> dict:
        cfg = load_project_config(root)
        manifest = load_manifest(root / cfg["codedoc"]["cache_dir"])
        return {
            "running": job.running,
            "progress": job.progress,
            "manifest": manifest_summary(manifest),
            "tools": tools_status(root, cfg),
            "config": {"languages": active_languages(root, cfg), "ignore": cfg["ignore"]},
        }

    @app.get("/__api/codedoc/status")
    async def api_codedoc_status() -> dict:
        return _codedoc_status()

    @app.get("/__api/codedoc/files")
    async def api_codedoc_files() -> list[str]:
        cfg = load_project_config(root)
        manifest = load_manifest(root / cfg["codedoc"]["cache_dir"])
        files: set[str] = set()
        for payload in (manifest.get("languages") or {}).values():
            files.update((payload.get("files") or {}).keys())
        return sorted(files)

    @app.post("/__api/codedoc/build")
    async def api_codedoc_build(request: Request) -> dict:
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        force = bool(body.get("force"))
        languages = body.get("languages")
        if languages is not None and not isinstance(languages, list):
            raise HTTPException(status_code=400, detail="languages must be a list")
        with job.lock:
            if job.running:
                raise HTTPException(status_code=409, detail="A code-doc build is already running")
            job.running = True
            job.cancel = threading.Event()
            job.progress = {
                "phase": "start",
                "done": 0,
                "total": 0,
                "current": "",
                "errors": [],
                "language": "",
            }

        def run() -> None:
            def on_progress(progress) -> None:
                job.progress = {
                    "phase": progress.phase,
                    "done": progress.done,
                    "total": progress.total,
                    "current": progress.current,
                    "errors": list(progress.errors),
                    "language": progress.language,
                }

            try:
                build(
                    root,
                    languages=languages,
                    progress=on_progress,
                    cancel=job.cancel,
                    force=force,
                )
            except Exception as exc:
                job.progress = {**job.progress, "phase": "error", "errors": [*job.progress["errors"], str(exc)]}
            finally:
                job.running = False
                loop = app.state.loop
                if loop is not None:
                    loop.call_soon_threadsafe(event_queue.put_nowait, str(root / "__codedoc__"))

        job.thread = threading.Thread(target=run, name="codedoc-build", daemon=True)
        job.thread.start()
        return _codedoc_status()

    @app.post("/__api/codedoc/cancel")
    async def api_codedoc_cancel() -> dict:
        job.cancel.set()
        return _codedoc_status()

    @app.post("/__api/plantuml")
    async def api_plantuml(request: Request) -> Response:
        source = (await request.body()).decode("utf-8", errors="replace")
        try:
            svg = render_plantuml_svg(source)
        except PlantUMLError as exc:
            return Response(content=str(exc), status_code=400, media_type="text/plain; charset=utf-8")
        return Response(content=svg, media_type="image/svg+xml; charset=utf-8")

    @app.get("/__api/config")
    async def api_get_config() -> dict:
        return public_config()

    @app.put("/__api/config")
    async def api_put_config(request: Request) -> dict:
        try:
            patch = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON") from exc
        if not isinstance(patch, dict):
            raise HTTPException(status_code=400, detail="Expected a JSON object")
        update_config(patch)
        return public_config()

    @app.get("/__file/{file_path:path}")
    async def serve_raw_file(file_path: str) -> Response:
        path = resolve_under_root(file_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Not found")
        media_type, _ = mimetypes.guess_type(str(path))
        return Response(content=path.read_bytes(), media_type=media_type or "application/octet-stream")

    @app.get("/__assets/pygments.css")
    async def pygments_stylesheet() -> Response:
        cfg = load_config()
        css = pygments_css(
            light_style=cfg["styles"]["light"],
            dark_style=cfg["styles"]["dark"],
        )
        return Response(content=css, media_type="text/css; charset=utf-8")

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
        return page_shell(root, root.name, preferred or "", files)

    @app.get("/{file_path:path}")
    async def serve_path(file_path: str, request: Request) -> Response:
        path = resolve_under_root(file_path)

        if path.is_dir():
            rel = path.relative_to(root).as_posix()
            prefix = "" if rel == "." else rel + "/"
            files = list_sidebar_files()
            under = [f for f in files if f.startswith(prefix) or rel == "."]
            preferred = under[0] if under else ""
            return HTMLResponse(page_shell(root, root.name, preferred, files))

        if not path.is_file():
            raise HTTPException(status_code=404, detail="Not found")

        suffix = path.suffix.lower()
        accept = request.headers.get("accept", "")
        if suffix in CODE_SUFFIXES | SIDEBAR_SUFFIXES and _wants_document(accept):
            files = list_sidebar_files()
            rel = path.relative_to(root).as_posix()
            return HTMLResponse(page_shell(root, root.name, rel, files))

        # Linked assets (markdown images, css, fonts, etc.)
        media_type, _ = mimetypes.guess_type(str(path))
        return Response(content=path.read_bytes(), media_type=media_type or "application/octet-stream")

    return app



ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_UI_ASSET_SUFFIXES = {".js", ".css", ".mjs", ".map", ".woff", ".woff2", ".ttf", ".otf", ".png"}


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


def page_shell(root: Path, title: str, active: str, files: list[str]) -> str:
    cfg = public_config()
    boot = json.dumps(
        {
            "initialPath": active,
            "files": files,
            "config": {
                "theme": cfg["theme"],
                "styles": cfg["styles"],
                "fonts": cfg["fonts"],
                "sidebars": cfg["sidebars"],
                "text": cfg["text"],
                "tables": cfg["tables"],
                "codedoc": cfg["codedoc"],
                "available_styles": cfg["available_styles"],
            },
            "codedoc": boot_status(root, load_project_config(root)),
        },
        ensure_ascii=False,
    ).replace("<", "\\u003c")
    template = (ASSETS_DIR / "index.html").read_text(encoding="utf-8")
    return (
        template
        .replace("__TITLE__", html.escape(title))
        .replace("__THEME__", html.escape(cfg["theme"]))
        .replace("__FONT_SANS__", font_stack_css(cfg["fonts"]["sans"]))
        .replace("__FONT_MONO__", font_stack_css(cfg["fonts"]["mono"]))
        .replace("__WRAP_CSS__", wrap_css_vars(cfg))
        .replace("__BOOT_JSON__", boot)
    )
