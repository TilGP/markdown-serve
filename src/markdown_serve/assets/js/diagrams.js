import { content } from "./dom.js";
import { state } from "./state.js";
import { mermaid } from "./theme.js";

const SERVER_DIAGRAMS = [
  { kind: "plantuml", endpoint: "/__api/plantuml", label: "PlantUML" },
  { kind: "excalidraw", endpoint: "/__api/excalidraw", label: "Excalidraw" },
];

let serverCache = new Map(); // kind -> Map(source -> { svg, width, height })
let serverCachePath = null;

export function resetServerDiagramCacheIfNeeded(path) {
  if (serverCachePath !== path) {
    serverCache = new Map();
    serverCachePath = path;
  }
}

function cacheFor(kind) {
  let cache = serverCache.get(kind);
  if (!cache) {
    cache = new Map();
    serverCache.set(kind, cache);
  }
  return cache;
}

function nodesFor(kind) {
  return [...content.querySelectorAll(".diagram-" + kind)];
}

export async function renderDiagrams() {
  for (const node of [...content.querySelectorAll(".diagram-mermaid")]) {
    const source = node.querySelector(".diagram-source")?.textContent ?? "";
    if (!source.trim()) continue;
    const id = "mermaid-" + (++state.mermaidId);
    try {
      const { svg } = await mermaid.render(id, source);
      node.innerHTML = svg;
    } catch (err) {
      node.innerHTML = '<div class="diagram-error">Mermaid error: ' +
        (err && err.message ? err.message : String(err)) + "</div>";
    }
  }
  await Promise.all(SERVER_DIAGRAMS.map((spec) => renderServerDiagrams(spec)));
}

export function snapshotServerDiagrams() {
  const snapshots = {};
  for (const spec of SERVER_DIAGRAMS) {
    snapshots[spec.kind] = nodesFor(spec.kind).map((node) => {
      const source = node.querySelector(".diagram-source")?.textContent ?? "";
      const svg = node.querySelector("svg");
      const target = svg || node.querySelector(".diagram-skeleton") || node;
      const rect = target.getBoundingClientRect();
      const cached = cacheFor(spec.kind).get(source);
      return {
        source,
        width: Math.max(0, Math.round(rect.width)) || cached?.width || 0,
        height: Math.max(0, Math.round(rect.height)) || cached?.height || 0,
        svg: svg ? svg.outerHTML : (cached?.svg ?? ""),
      };
    });
  }
  return snapshots;
}

function sourceHtml(node) {
  return node.querySelector(".diagram-source")?.outerHTML ?? "";
}

function setSkeleton(node, width, height) {
  const w = width > 0 ? `${width}px` : "100%";
  const h = height > 0 ? `${height}px` : "8rem";
  node.style.minHeight = height > 0 ? `${height}px` : "";
  node.innerHTML = sourceHtml(node) +
    `<div class="diagram-skeleton" style="width:${w};max-width:100%;height:${h};min-height:${h}" aria-hidden="true"></div>`;
}

function setSvg(node, kind, svg, { reserveHeight = 0 } = {}) {
  const kept = sourceHtml(node);
  if (reserveHeight > 0) {
    node.style.minHeight = `${reserveHeight}px`;
  }
  node.innerHTML = kept + svg;
  const rendered = node.querySelector("svg") || node;
  const rect = rendered.getBoundingClientRect();
  const source = node.querySelector(".diagram-source")?.textContent ?? "";
  const width = Math.max(0, Math.round(rect.width));
  const height = Math.max(0, Math.round(rect.height), reserveHeight);
  if (source.trim()) {
    cacheFor(kind).set(source, { svg, width, height });
  }
  // Keep reserved height until the SVG has painted at full size.
  requestAnimationFrame(() => {
    const next = node.getBoundingClientRect().height;
    if (next >= reserveHeight - 1) node.style.minHeight = "";
  });
}

export function prepareServerDiagramPlaceholders(snapshots) {
  for (const spec of SERVER_DIAGRAMS) {
    const list = snapshots?.[spec.kind] || [];
    const bySource = new Map();
    for (const snap of list) {
      if (snap.source.trim() && !bySource.has(snap.source)) {
        bySource.set(snap.source, snap);
      }
    }
    nodesFor(spec.kind).forEach((node, index) => {
      const source = node.querySelector(".diagram-source")?.textContent ?? "";
      if (!source.trim()) return;

      const cached = cacheFor(spec.kind).get(source);
      const prev = bySource.get(source) || list[index];
      const height = cached?.height || prev?.height || 0;
      const width = cached?.width || prev?.width || 0;

      if (cached?.svg) {
        setSvg(node, spec.kind, cached.svg, { reserveHeight: height });
        return;
      }

      setSkeleton(node, width, height);
    });
  }
}

async function renderServerDiagrams(spec) {
  await Promise.all(nodesFor(spec.kind).map(async (node) => {
    const source = node.querySelector(".diagram-source")?.textContent ?? "";
    if (!source.trim()) return;

    const cached = cacheFor(spec.kind).get(source);
    if (cached?.svg && node.querySelector("svg") && !node.querySelector(".diagram-skeleton")) {
      return;
    }

    if (!node.querySelector(".diagram-skeleton") && !node.querySelector("svg")) {
      const rect = node.getBoundingClientRect();
      setSkeleton(node, Math.round(rect.width), Math.round(rect.height) || 0);
    }

    const reserved = Math.round(node.getBoundingClientRect().height) || cached?.height || 0;

    try {
      const res = await fetch(spec.endpoint, {
        method: "POST",
        headers: { "Content-Type": "text/plain; charset=utf-8" },
        body: source,
      });
      const text = await res.text();
      if (!res.ok) {
        throw new Error(text || res.statusText);
      }
      setSvg(node, spec.kind, text, { reserveHeight: reserved });
      fitWideTables();
    } catch (err) {
      node.style.minHeight = "";
      node.innerHTML = sourceHtml(node) +
        `<div class="diagram-error">${spec.label} error: ` +
        (err && err.message ? err.message : String(err)) + "</div>";
    }
  }));
}

export function fitWideTables() {
  if (content.classList.contains("asset-mode")) return;
  const column = content.parentElement;
  if (!column) return;
  // Reset to the CSS width (derived from --text-width) and measure it as the floor.
  column.style.width = "";
  column.style.minWidth = "";
  const base = column.getBoundingClientRect().width;
  let widest = 0;
  for (const table of content.querySelectorAll("table")) {
    widest = Math.max(widest, table.scrollWidth);
  }
  for (const spec of SERVER_DIAGRAMS) {
    for (const diagram of nodesFor(spec.kind)) {
      widest = Math.max(widest, diagram.scrollWidth);
      const svg = diagram.querySelector("svg");
      if (svg) {
        const attrWidth = Number.parseFloat(svg.getAttribute("width") || "");
        const viewBox = svg.viewBox?.baseVal;
        const natural = Number.isFinite(attrWidth) && attrWidth > 0
          ? attrWidth
          : (viewBox && viewBox.width > 0 ? viewBox.width : svg.scrollWidth);
        widest = Math.max(widest, natural);
      }
    }
  }
  if (widest <= 0) return;
  const style = getComputedStyle(content);
  const pad = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
  const border = parseFloat(style.borderLeftWidth) + parseFloat(style.borderRightWidth);
  const needed = Math.ceil(widest + pad + border);
  const width = Math.max(base, needed);
  column.style.width = width + "px";
  column.style.minWidth = width + "px";
}
