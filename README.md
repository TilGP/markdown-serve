# markdown-serve

**A local live Markdown viewer for the folder you’re working in.**

Point it at a notes tree, a docs repo, or any project with `.md` files. You get a file sidebar, instant preview, and automatic reload when you save — no cloud, no CDN, no plantuml.com.

<p align="center">
  <img src="readme_files/combined.png" alt="markdown-serve light and dark themes, split diagonally" width="900" />
</p>

<p align="center"><em>Light and dark theme in one glance — same layout, same diagrams.</em></p>

## What you get

| | |
|---|---|
| **Browse the tree** | Sidebar lists Markdown, images, and PDFs under the serve root. Fuzzy find with `/`, or prefix with `'` for exact match. |
| **Live preview** | Edits on disk refresh the browser over a WebSocket. Save and the page updates. |
| **Real rendering** | Tables, syntax-highlighted code ([Pygments](https://pygments.org/)), images, linked assets, PDF iframe preview. |
| **Diagrams** | [`mermaid`](https://mermaid.js.org/) and [`plantuml`](https://plantuml.com/) / `puml` fences render in place — Mermaid in the browser, PlantUML via local Java. |
| **Themes** | Light/dark toggle (persisted). **Right-click the theme button** to show a Pygments style picker for the current theme (code highlighting). |
| **Offline-first** | UI, Mermaid, and PlantUML jar ship with the project. Works on a plane. |

Wide tables and PlantUML SVGs expand the content panel instead of getting squashed.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and a JRE (`java` on `PATH`) for PlantUML.

```bash
git clone <this-repo>
cd markdown-serve
uv sync
export PATH="$PWD/bin:$PATH"
```

From any directory that has Markdown:

```bash
markdown-serve
```

Opens `http://127.0.0.1:8765` and serves the current working directory.

| Flag | Description |
|------|-------------|
| `-p`, `--port` | Port (default `8765`) |
| `--host` | Bind address (default `127.0.0.1`) |
| `-r`, `--root` | Directory to serve (default: CWD) |
| `--no-open` | Don’t open a browser |

## Diagrams

Fenced blocks just work:

````markdown
```mermaid
flowchart LR
  A[Start] --> B[Done]
```

```plantuml
@startuml
Alice -> Bob: hello
@enduml
```
````

[Mermaid](https://mermaid.js.org/) uses the vendored browser script. [PlantUML](https://plantuml.com/) runs locally (`java -jar` on the bundled LGPL jar, or a `plantuml` binary on `PATH`).

## Configuration

On first run, `src/markdown_serve/config.json` is created with defaults if it is missing.
It holds theme, [Pygments](https://pygments.org/) styles, and font stacks:

```json
{
  "theme": "light",
  "styles": { "light": "default", "dark": "nord" },
  "fonts": {
    "sans": ["Avenir Next", "Segoe UI", "system-ui", "sans-serif"],
    "mono": ["Fira Code", "ui-monospace", "monospace"]
  }
}
```

Left-click the sun/moon button to toggle light and dark. **Right-click it** to reveal the code-highlighting style dropdown for the active theme (any installed Pygments style). Choices are written back to this file. Fonts are config-only (no picker). The file is gitignored so local preferences stay on your machine.

## Third-party / offline assets

Vendored under `src/markdown_serve/assets/vendor/`:

- **[Mermaid](https://mermaid.js.org/)** (MIT) — `mermaid.min.js`
- **[PlantUML](https://plantuml.com/)** (LGPL jar, unmodified) — `plantuml.jar`

Code blocks are highlighted with **[Pygments](https://pygments.org/)** (Python dependency, not vendored as a static asset).

markdown-serve uses PlantUML, which is distributed under the LGPL. Details: `src/markdown_serve/assets/vendor/README.md`.
