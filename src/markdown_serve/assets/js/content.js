import { content, printPageBtn } from "./dom.js";
import { state } from "./state.js";
import {
  basename, dirname, encodePath, escapeHtml, fileKind,
} from "./utils.js";
import { markActive } from "./nav.js";
import { clearToc, updateToc } from "./toc.js";
import {
  fitWideTables,
  preparePlantumlPlaceholders,
  renderDiagrams,
  resetPlantumlCacheIfNeeded,
  snapshotPlantumlLayout,
} from "./diagrams.js";
import { enhanceZoomables } from "./lightbox.js";

function setPrintVisible(visible) {
  if (!printPageBtn) return;
  printPageBtn.hidden = !visible;
}

function resolveLocalTarget(href, fromPath) {
  if (!href) return null;
  const raw = href.trim();
  if (
    !raw ||
    raw.startsWith("#") ||
    raw.startsWith("mailto:") ||
    raw.startsWith("tel:") ||
    raw.startsWith("javascript:") ||
    raw.startsWith("data:")
  ) {
    return null;
  }
  try {
    const baseDir = dirname(fromPath);
    const base = "https://markdown-serve.local/" + (baseDir ? encodePath(baseDir) + "/" : "");
    const url = new URL(raw, base);
    if (url.origin !== "https://markdown-serve.local") return null;
    let path = decodeURIComponent(url.pathname.replace(/^\/+/, ""));
    if (!path || path.startsWith("__")) return null;
    // Normalize ./ and ../ segments
    const parts = [];
    for (const part of path.split("/")) {
      if (!part || part === ".") continue;
      if (part === "..") {
        if (parts.length) parts.pop();
        continue;
      }
      parts.push(part);
    }
    return parts.join("/");
  } catch (_) {
    return null;
  }
}

async function markBrokenLinks(fromPath) {
  const token = ++state.brokenLinkToken;
  const anchors = [...content.querySelectorAll("a[href]")];
  await Promise.all(anchors.map(async (a) => {
    if (a.classList.contains("headerlink")) return;
    const target = resolveLocalTarget(a.getAttribute("href"), fromPath);
    if (!target) return;
    try {
      const res = await fetch("/__api/exists/" + encodePath(target));
      if (token !== state.brokenLinkToken) return;
      if (!res.ok) return;
      const data = await res.json();
      if (token !== state.brokenLinkToken) return;
      if (!data.exists) {
        a.classList.add("broken-link");
        a.title = "Missing file: " + target;
        a.setAttribute("aria-description", "Linked file does not exist");
      }
    } catch (_) {
      // Ignore network errors while checking links.
    }
  }));
}

function captureScrollAnchor() {
  const scroller = document.scrollingElement || document.documentElement;
  const scrollY = scroller.scrollTop;
  const probeY = 64;
  const blocks = content.querySelectorAll(
    "h1, h2, h3, h4, h5, h6, p, li, pre, table, blockquote, .diagram, .highlight",
  );
  let anchor = null;
  for (const el of blocks) {
    const rect = el.getBoundingClientRect();
    if (rect.bottom <= probeY) continue;
    if (rect.top > window.innerHeight) break;
    anchor = {
      id: el.id || "",
      text: (el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 96),
      tag: el.tagName.toLowerCase(),
      offset: rect.top,
    };
    break;
  }
  return { scrollY, anchor };
}

function restoreScrollAnchor(stateScroll) {
  if (!stateScroll) return;
  const scroller = document.scrollingElement || document.documentElement;
  const anchor = stateScroll.anchor;
  if (anchor) {
    let el = null;
    if (anchor.id) {
      try {
        el = content.querySelector("#" + CSS.escape(anchor.id));
      } catch (_) {
        el = document.getElementById(anchor.id);
        if (el && !content.contains(el)) el = null;
      }
    }
    if (!el && anchor.text) {
      const needle = anchor.text.slice(0, 48);
      const candidates = content.querySelectorAll(anchor.tag || "p, h1, h2, h3, h4, li, pre");
      for (const candidate of candidates) {
        const text = (candidate.innerText || "").replace(/\s+/g, " ").trim();
        if (text.startsWith(needle) || text.includes(needle)) {
          el = candidate;
          break;
        }
      }
    }
    if (el) {
      const delta = el.getBoundingClientRect().top - anchor.offset;
      if (Math.abs(delta) > 0.5) {
        scroller.scrollTop += delta;
      }
      return;
    }
  }
  scroller.scrollTop = stateScroll.scrollY;
}

function lineNeedle(rawLine) {
  return rawLine
    .replace(/^\s*#{1,6}\s+/, "")
    .replace(/^\s*[-*+]\s+/, "")
    .replace(/^\s*\d+\.\s+/, "")
    .replace(/^\s*>\s+/, "")
    .replace(/`+/g, "")
    .trim();
}

function scrollToSourceLine(sourceText, lineNum) {
  content.querySelectorAll(".line-flash").forEach((el) => el.classList.remove("line-flash"));
  const lines = sourceText.split(/\r?\n/);
  if (lineNum < 1 || lineNum > lines.length) return;

  const needle = lineNeedle(lines[lineNum - 1]);
  let target = null;
  if (needle.length >= 2) {
    const needleLower = needle.toLowerCase();
    const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (!node.nodeValue || !node.nodeValue.toLowerCase().includes(needleLower)) continue;
      target = node.parentElement;
      break;
    }
  }
  if (!target) {
    const blocks = [...content.querySelectorAll("p, li, h1, h2, h3, h4, h5, h6, pre, td, th, blockquote")];
    if (blocks.length) {
      const idx = Math.min(
        blocks.length - 1,
        Math.max(0, Math.round(((lineNum - 1) / Math.max(lines.length - 1, 1)) * (blocks.length - 1))),
      );
      target = blocks[idx];
    }
  }
  if (!target) return;
  target.classList.add("line-flash");
  target.scrollIntoView({ behavior: "smooth", block: "center" });
}

export async function load(path, { line = null } = {}) {
  if (!path) {
    content.classList.remove("asset-mode");
    content.innerHTML = '<p class="empty">Select a file.</p>';
    clearToc();
    setPrintVisible(false);
    return;
  }
  const previousPath = state.currentPath;
  const preserveScroll = previousPath === path && (line == null || line <= 0);
  const kind = fileKind(path);
  state.currentPath = path;
  document.title = path + " — markdown-serve";
  const lineQuery = line != null && line > 0 ? "?line=" + String(line) : "";
  history.replaceState(null, "", "/" + encodePath(path) + lineQuery);
  markActive(path);
  setPrintVisible(kind === "markdown");

  if (kind === "image") {
    content.classList.add("asset-mode");
    const column = content.parentElement;
    if (column) {
      column.style.width = "";
      column.style.minWidth = "";
    }
    content.innerHTML = '<img class="asset-preview" src="/__file/' +
      encodePath(path) + '" alt="' + escapeHtml(basename(path)) + '">';
    enhanceZoomables();
    clearToc();
    return;
  }
  if (kind === "pdf") {
    content.classList.add("asset-mode");
    const column = content.parentElement;
    if (column) {
      column.style.width = "";
      column.style.minWidth = "";
    }
    content.innerHTML = '<iframe class="pdf-preview" title="' +
      escapeHtml(basename(path)) + '" src="/__file/' + encodePath(path) + '"></iframe>';
    clearToc();
    return;
  }

  content.classList.remove("asset-mode");
  const res = await fetch("/__api/render/" + encodePath(path));
  if (!res.ok) {
    content.innerHTML = '<p class="empty">Failed to load ' + escapeHtml(path) + "</p>";
    clearToc();
    setPrintVisible(false);
    return;
  }
  const data = await res.json();
  resetPlantumlCacheIfNeeded(path);
  const scrollState = preserveScroll ? captureScrollAnchor() : null;
  const plantumlSnapshots = snapshotPlantumlLayout();
  content.innerHTML = data.html;
  preparePlantumlPlaceholders(plantumlSnapshots);
  updateToc();
  await renderDiagrams();
  enhanceZoomables();
  fitWideTables();
  await markBrokenLinks(path);
  if (line != null && line > 0) {
    requestAnimationFrame(() => scrollToSourceLine(data.text || "", line));
  } else if (scrollState) {
    restoreScrollAnchor(scrollState);
    requestAnimationFrame(() => {
      restoreScrollAnchor(scrollState);
      // Mermaid/PlantUML may still settle one frame later.
      requestAnimationFrame(() => restoreScrollAnchor(scrollState));
    });
  } else if (previousPath !== path) {
    const scroller = document.scrollingElement || document.documentElement;
    scroller.scrollTop = 0;
  }
}

export function initPrint() {
  if (!printPageBtn) return;
  printPageBtn.addEventListener("click", () => {
    window.print();
  });
}
