import { content } from "./dom.js";
import { state } from "./state.js";
import { mermaid } from "./theme.js";

let plantumlCache = new Map(); // source -> { svg, width, height }
let plantumlCachePath = null;

export function resetPlantumlCacheIfNeeded(path) {
  if (plantumlCachePath !== path) {
    plantumlCache = new Map();
    plantumlCachePath = path;
  }
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
  await renderPlantumlDiagrams();
}

export function snapshotPlantumlLayout() {
  return [...content.querySelectorAll(".diagram-plantuml")].map((node) => {
    const source = node.querySelector(".diagram-source")?.textContent ?? "";
    const svg = node.querySelector("svg");
    const target = svg || node.querySelector(".diagram-skeleton") || node;
    const rect = target.getBoundingClientRect();
    const cached = plantumlCache.get(source);
    return {
      source,
      width: Math.max(0, Math.round(rect.width)) || cached?.width || 0,
      height: Math.max(0, Math.round(rect.height)) || cached?.height || 0,
      svg: svg ? svg.outerHTML : (cached?.svg ?? ""),
    };
  });
}

function plantumlSourceHtml(node) {
  return node.querySelector(".diagram-source")?.outerHTML ?? "";
}

function setPlantumlSkeleton(node, width, height) {
  const sourceHtml = plantumlSourceHtml(node);
  const w = width > 0 ? `${width}px` : "100%";
  const h = height > 0 ? `${height}px` : "8rem";
  node.style.minHeight = height > 0 ? `${height}px` : "";
  node.innerHTML = sourceHtml +
    `<div class="diagram-skeleton" style="width:${w};max-width:100%;height:${h};min-height:${h}" aria-hidden="true"></div>`;
}

function setPlantumlSvg(node, svg, { reserveHeight = 0 } = {}) {
  const sourceHtml = plantumlSourceHtml(node);
  if (reserveHeight > 0) {
    node.style.minHeight = `${reserveHeight}px`;
  }
  node.innerHTML = sourceHtml + svg;
  const rendered = node.querySelector("svg") || node;
  const rect = rendered.getBoundingClientRect();
  const source = node.querySelector(".diagram-source")?.textContent ?? "";
  const width = Math.max(0, Math.round(rect.width));
  const height = Math.max(0, Math.round(rect.height), reserveHeight);
  if (source.trim()) {
    plantumlCache.set(source, { svg, width, height });
  }
  // Keep reserved height until the SVG has painted at full size.
  requestAnimationFrame(() => {
    const next = node.getBoundingClientRect().height;
    if (next >= reserveHeight - 1) node.style.minHeight = "";
  });
}

export function preparePlantumlPlaceholders(snapshots) {
  const bySource = new Map();
  for (const snap of snapshots) {
    if (snap.source.trim() && !bySource.has(snap.source)) {
      bySource.set(snap.source, snap);
    }
  }
  const nodes = [...content.querySelectorAll(".diagram-plantuml")];
  nodes.forEach((node, index) => {
    const source = node.querySelector(".diagram-source")?.textContent ?? "";
    if (!source.trim()) return;

    const cached = plantumlCache.get(source);
    const prev = bySource.get(source) || snapshots[index];
    const height = cached?.height || prev?.height || 0;
    const width = cached?.width || prev?.width || 0;

    if (cached?.svg) {
      setPlantumlSvg(node, cached.svg, { reserveHeight: height });
      return;
    }

    setPlantumlSkeleton(node, width, height);
  });
}

async function renderPlantumlDiagrams() {
  const nodes = [...content.querySelectorAll(".diagram-plantuml")];
  await Promise.all(nodes.map(async (node) => {
    const source = node.querySelector(".diagram-source")?.textContent ?? "";
    if (!source.trim()) return;

    const cached = plantumlCache.get(source);
    if (cached?.svg && node.querySelector("svg") && !node.querySelector(".diagram-skeleton")) {
      return;
    }

    if (!node.querySelector(".diagram-skeleton") && !node.querySelector("svg")) {
      const rect = node.getBoundingClientRect();
      setPlantumlSkeleton(node, Math.round(rect.width), Math.round(rect.height) || 0);
    }

    const reserved = Math.round(node.getBoundingClientRect().height) || cached?.height || 0;

    try {
      const res = await fetch("/__api/plantuml", {
        method: "POST",
        headers: { "Content-Type": "text/plain; charset=utf-8" },
        body: source,
      });
      const text = await res.text();
      if (!res.ok) {
        throw new Error(text || res.statusText);
      }
      setPlantumlSvg(node, text, { reserveHeight: reserved });
      fitWideTables();
    } catch (err) {
      node.style.minHeight = "";
      const sourceHtml = plantumlSourceHtml(node);
      node.innerHTML = sourceHtml +
        '<div class="diagram-error">PlantUML error: ' +
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
  for (const diagram of content.querySelectorAll(".diagram-plantuml")) {
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
  if (widest <= 0) return;
  const style = getComputedStyle(content);
  const pad = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
  const border = parseFloat(style.borderLeftWidth) + parseFloat(style.borderRightWidth);
  const needed = Math.ceil(widest + pad + border);
  const width = Math.max(base, needed);
  column.style.width = width + "px";
  column.style.minWidth = width + "px";
}
