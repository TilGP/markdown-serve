"""Live markdown preview server."""

from __future__ import annotations

import asyncio
import html
import json
import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from markdown_serve.render import pygments_css, render_markdown

MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkd"}
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".tox", ".mypy_cache"}


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

    def list_markdown_files() -> list[str]:
        files: list[str] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in MARKDOWN_SUFFIXES:
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
        return list_markdown_files()

    @app.get("/__api/render/{file_path:path}")
    async def api_render(file_path: str) -> dict[str, str]:
        path = resolve_under_root(file_path)
        if not path.is_file() or path.suffix.lower() not in MARKDOWN_SUFFIXES:
            raise HTTPException(status_code=404, detail="Markdown file not found")
        text = path.read_text(encoding="utf-8")
        return {"path": file_path, "html": render_markdown(text)}

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        files = list_markdown_files()
        preferred = next(
            (f for f in ("README.md", "readme.md", "index.md", "INDEX.md") if f in files),
            files[0] if files else None,
        )
        return page_shell(root.name, preferred or "", files)

    @app.get("/{file_path:path}")
    async def serve_path(file_path: str) -> Response:
        path = resolve_under_root(file_path)

        if path.is_dir():
            # Directory index of markdown files under this folder
            rel = path.relative_to(root).as_posix()
            prefix = "" if rel == "." else rel + "/"
            files = [f for f in list_markdown_files() if f.startswith(prefix) or rel == "."]
            preferred = files[0] if files else ""
            return HTMLResponse(page_shell(root.name, preferred, files))

        if not path.is_file():
            raise HTTPException(status_code=404, detail="Not found")

        if path.suffix.lower() in MARKDOWN_SUFFIXES:
            files = list_markdown_files()
            rel = path.relative_to(root).as_posix()
            return HTMLResponse(page_shell(root.name, rel, files))

        # Serve linked assets (images, css, pdf, etc.)
        media_type, _ = mimetypes.guess_type(str(path))
        return Response(content=path.read_bytes(), media_type=media_type or "application/octet-stream")

    return app


def page_shell(title: str, active: str, files: list[str]) -> str:
    initial = html.escape(active)
    files_json = json.dumps(files).replace("<", "\\u003c")
    css = pygments_css()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} — markdown-serve</title>
  <style>
    :root {{
      --bg: #f7f6f2;
      --panel: #ffffff;
      --ink: #1c1917;
      --muted: #78716c;
      --line: #e7e5e4;
      --accent: #0f766e;
      --accent-soft: #ccfbf1;
      --code-bg: #f5f5f4;
      --sidebar-w: 300px;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; height: 100%; }}
    body {{
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(ellipse 80% 50% at 0% 0%, #d1fae5 0%, transparent 50%),
        radial-gradient(ellipse 60% 40% at 100% 100%, #fef3c7 0%, transparent 45%),
        var(--bg);
    }}
    .layout {{
      display: grid;
      grid-template-columns: var(--sidebar-w) 1fr;
      min-height: 100vh;
    }}
    aside {{
      border-right: 1px solid var(--line);
      background: color-mix(in srgb, var(--panel) 88%, transparent);
      backdrop-filter: blur(8px);
      padding: 1.25rem 0.75rem;
      overflow: auto;
      position: sticky;
      top: 0;
      height: 100vh;
    }}
    .brand {{
      font-family: "IBM Plex Mono", ui-monospace, monospace;
      font-size: 0.75rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--muted);
      padding: 0 0.75rem 1rem;
    }}
    .brand strong {{ color: var(--accent); font-weight: 600; }}
    .tree, .tree ul {{
      list-style: none;
      margin: 0;
      padding: 0;
    }}
    .tree ul {{
      padding-left: 0.85rem;
      margin-left: 0.35rem;
      border-left: 1px solid var(--line);
    }}
    .tree li {{ margin: 0.05rem 0; }}
    .tree details > summary {{
      list-style: none;
      cursor: pointer;
      user-select: none;
      display: flex;
      align-items: center;
      gap: 0.35rem;
      padding: 0.3rem 0.5rem;
      border-radius: 6px;
      font-size: 0.8rem;
      font-weight: 560;
      color: var(--muted);
    }}
    .tree details > summary::-webkit-details-marker {{ display: none; }}
    .tree details > summary::before {{
      content: "";
      width: 0;
      height: 0;
      border-top: 4px solid transparent;
      border-bottom: 4px solid transparent;
      border-left: 5px solid var(--muted);
      transition: transform 0.12s ease;
      flex: 0 0 auto;
    }}
    .tree details[open] > summary::before {{
      transform: rotate(90deg);
    }}
    .tree details > summary:hover {{ background: var(--code-bg); color: var(--ink); }}
    .tree .folder-name {{
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .nav-link {{
      display: block;
      padding: 0.3rem 0.5rem;
      border-radius: 6px;
      color: var(--ink);
      text-decoration: none;
      font-size: 0.825rem;
      line-height: 1.35;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .nav-link:hover {{ background: var(--code-bg); }}
    .nav-link.active {{
      background: var(--accent-soft);
      color: var(--accent);
      font-weight: 560;
    }}
    .empty {{
      color: var(--muted);
      font-size: 0.875rem;
      padding: 0.75rem;
    }}
    main {{
      padding: 2rem clamp(1.25rem, 4vw, 3rem);
      min-width: 0;
      max-width: 100%;
      overflow-x: auto;
    }}
    #status {{
      font-family: "IBM Plex Mono", ui-monospace, monospace;
      font-size: 0.7rem;
      color: var(--muted);
      margin-bottom: 1rem;
      width: min(52rem, 100%);
    }}
    #status.live::before {{
      content: "";
      display: inline-block;
      width: 0.5rem;
      height: 0.5rem;
      border-radius: 50%;
      background: #16a34a;
      margin-right: 0.4rem;
      vertical-align: middle;
    }}
    #content {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: clamp(1.25rem, 3vw, 2.25rem);
      box-shadow: 0 1px 0 rgba(28, 25, 23, 0.04);
      box-sizing: border-box;
      width: min(52rem, 100%);
      min-width: min(52rem, 100%);
    }}
    #content :first-child {{ margin-top: 0; }}
    #content :last-child {{ margin-bottom: 0; }}
    #content h1, #content h2, #content h3, #content h4 {{
      font-family: "Source Serif 4", "Iowan Old Style", Georgia, serif;
      line-height: 1.25;
      font-weight: 600;
    }}
    #content h1 {{ font-size: 2rem; }}
    #content h2 {{
      font-size: 1.45rem;
      border-bottom: 1px solid var(--line);
      padding-bottom: 0.35rem;
      margin-top: 1.75rem;
    }}
    #content a {{ color: var(--accent); }}
    #content code {{
      font-family: "IBM Plex Mono", ui-monospace, monospace;
      font-size: 0.875em;
      background: var(--code-bg);
      padding: 0.1em 0.35em;
      border-radius: 4px;
    }}
    #content pre {{
      background: var(--code-bg);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0.9rem 1rem;
      overflow: auto;
    }}
    #content pre code {{ background: none; padding: 0; }}
    #content img {{ max-width: 100%; height: auto; }}
    #content blockquote {{
      margin-left: 0;
      padding-left: 1rem;
      border-left: 3px solid var(--accent);
      color: var(--muted);
    }}
    #content table {{
      border-collapse: collapse;
      width: max-content;
      max-width: none;
      margin: 1rem 0;
    }}
    #content th, #content td {{
      border: 1px solid var(--line);
      padding: 0.45rem 0.7rem;
      text-align: left;
      white-space: normal;
      max-width: 80ch;
      overflow-wrap: break-word;
      word-wrap: break-word;
    }}
    #content th {{ background: var(--code-bg); }}
    .diagram {{
      margin: 1.25rem 0;
      padding: 1rem;
      background: var(--code-bg);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: auto;
      text-align: center;
    }}
    .diagram .diagram-source {{ display: none; }}
    .diagram img, .diagram svg {{ max-width: 100%; height: auto; }}
    .diagram-error {{
      color: #b91c1c;
      font-family: "IBM Plex Mono", ui-monospace, monospace;
      font-size: 0.8rem;
      text-align: left;
      white-space: pre-wrap;
    }}
    {css}
    @media (max-width: 800px) {{
      .layout {{ grid-template-columns: 1fr; }}
      aside {{
        position: static;
        height: auto;
        border-right: none;
        border-bottom: 1px solid var(--line);
        max-height: 40vh;
      }}
    }}
  </style>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;560&family=Source+Serif+4:opsz,wght@8..60,600&display=swap" rel="stylesheet">
</head>
<body>
  <div class="layout">
    <aside>
      <div class="brand"><strong>markdown</strong>-serve</div>
      <nav id="nav"></nav>
    </aside>
    <main>
      <div id="status">connecting…</div>
      <article id="content"><p class="empty">Select a markdown file.</p></article>
    </main>
  </div>
  <script type="module">
    import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
    import plantumlEncoder from "https://cdn.jsdelivr.net/npm/plantuml-encoder@1.4.0/+esm";

    const PLANTUML_SERVER = "https://www.plantuml.com/plantuml/svg/";
    const initialPath = {initial!r};
    const initialFiles = {files_json};
    const content = document.getElementById("content");
    const status = document.getElementById("status");
    const nav = document.getElementById("nav");
    let currentPath = initialPath;
    let mermaidId = 0;

    mermaid.initialize({{
      startOnLoad: false,
      securityLevel: "loose",
      theme: "neutral",
    }});

    function buildTree(files) {{
      const root = {{ dirs: {{}}, files: [] }};
      for (const path of files) {{
        const parts = path.split("/");
        let node = root;
        for (let i = 0; i < parts.length - 1; i++) {{
          const part = parts[i];
          if (!node.dirs[part]) node.dirs[part] = {{ dirs: {{}}, files: [] }};
          node = node.dirs[part];
        }}
        node.files.push({{ name: parts[parts.length - 1], path }});
      }}
      return root;
    }}

    function escapeHtml(s) {{
      return s.replace(/[&<>"']/g, (c) => ({{
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }})[c]);
    }}

    function renderNode(node, active, prefix) {{
      const dirNames = Object.keys(node.dirs).sort((a, b) => a.localeCompare(b));
      const files = [...node.files].sort((a, b) => a.name.localeCompare(b.name));
      let html = "<ul class=\\"tree-level\\">";
      for (const name of dirNames) {{
        const childPrefix = prefix ? prefix + "/" + name : name;
        const open = !active || active === childPrefix || active.startsWith(childPrefix + "/");
        html += "<li><details" + (open ? " open" : "") + ">" +
          "<summary><span class=\\"folder-name\\">" + escapeHtml(name) + "</span></summary>" +
          renderNode(node.dirs[name], active, childPrefix) +
          "</details></li>";
      }}
      for (const file of files) {{
        const activeClass = file.path === active ? " active" : "";
        html += "<li><a href=\\"/" + escapeHtml(file.path) +
          "\\" class=\\"nav-link" + activeClass +
          "\\" data-path=\\"" + escapeHtml(file.path) +
          "\\" title=\\"" + escapeHtml(file.path) + "\\">" +
          escapeHtml(file.name) + "</a></li>";
      }}
      html += "</ul>";
      return html;
    }}

    function renderNav(files, active) {{
      if (!files.length) {{
        nav.innerHTML = '<p class="empty">No markdown files in this directory.</p>';
        return;
      }}
      nav.innerHTML = renderNode(buildTree(files), active, "").replace(
        'class="tree-level"', 'class="tree"'
      );
    }}

    async function renderDiagrams() {{
      const mermaidNodes = [...content.querySelectorAll(".diagram-mermaid")];
      for (const node of mermaidNodes) {{
        const source = node.querySelector(".diagram-source")?.textContent ?? "";
        if (!source.trim()) continue;
        const id = "mermaid-" + (++mermaidId);
        try {{
          const {{ svg }} = await mermaid.render(id, source);
          node.innerHTML = svg;
        }} catch (err) {{
          node.innerHTML = '<div class="diagram-error">Mermaid error: ' +
            (err && err.message ? err.message : String(err)) + "</div>";
        }}
      }}

      for (const node of content.querySelectorAll(".diagram-plantuml")) {{
        const source = node.querySelector(".diagram-source")?.textContent ?? "";
        if (!source.trim()) continue;
        const img = document.createElement("img");
        img.alt = "PlantUML diagram";
        img.src = PLANTUML_SERVER + plantumlEncoder.encode(source);
        img.onerror = () => {{
          node.innerHTML = '<div class="diagram-error">Failed to render PlantUML diagram. ' +
            "Check syntax or plantuml.com availability.</div>";
        }};
        node.replaceChildren(img);
      }}
    }}

    function fitWideTables() {{
      content.style.width = "";
      content.style.minWidth = "";
      const base = Math.min(52 * 16, content.parentElement.clientWidth);
      let widest = 0;
      for (const table of content.querySelectorAll("table")) {{
        widest = Math.max(widest, table.scrollWidth);
      }}
      if (widest <= 0) {{
        content.style.width = "min(52rem, 100%)";
        content.style.minWidth = "min(52rem, 100%)";
        return;
      }}
      const style = getComputedStyle(content);
      const pad = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
      const border = parseFloat(style.borderLeftWidth) + parseFloat(style.borderRightWidth);
      const needed = Math.ceil(widest + pad + border);
      const width = Math.max(base, needed);
      content.style.width = width + "px";
      content.style.minWidth = width + "px";
    }}

    async function load(path) {{
      if (!path) {{
        content.innerHTML = '<p class="empty">No markdown file selected.</p>';
        return;
      }}
      const res = await fetch("/__api/render/" + encodeURI(path));
      if (!res.ok) {{
        content.innerHTML = '<p class="empty">Failed to load ' + path + '</p>';
        return;
      }}
      const data = await res.json();
      content.innerHTML = data.html;
      currentPath = path;
      document.title = path + " — markdown-serve";
      history.replaceState(null, "", "/" + path);
      nav.querySelectorAll(".nav-link").forEach((a) => {{
        a.classList.toggle("active", a.dataset.path === path);
      }});
      // Expand ancestors of the active file
      nav.querySelectorAll("details").forEach((d) => {{
        const link = d.querySelector(".nav-link.active");
        if (link) d.open = true;
      }});
      await renderDiagrams();
      fitWideTables();
    }}

    window.addEventListener("resize", fitWideTables);
    nav.addEventListener("click", (e) => {{
      const a = e.target.closest("a.nav-link");
      if (!a) return;
      e.preventDefault();
      load(a.dataset.path);
    }});

    function connect() {{
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(proto + "://" + location.host + "/__ws");
      ws.onopen = () => {{
        status.textContent = "live";
        status.classList.add("live");
      }};
      ws.onclose = () => {{
        status.textContent = "reconnecting…";
        status.classList.remove("live");
        setTimeout(connect, 800);
      }};
      ws.onmessage = async (ev) => {{
        const changed = ev.data;
        try {{
          const res = await fetch("/__api/files");
          const files = await res.json();
          renderNav(files, currentPath);
          if (!currentPath && files.length) currentPath = files[0];
          if (currentPath) await load(currentPath);
          else if (changed.endsWith(".md")) await load(changed);
        }} catch (_) {{
          if (currentPath) await load(currentPath);
        }}
      }};
    }}

    renderNav(initialFiles, initialPath);
    load(initialPath);
    connect();
  </script>
</body>
</html>
"""
