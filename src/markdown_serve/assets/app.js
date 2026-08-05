const boot = JSON.parse(document.getElementById("markdown-serve-boot").textContent);
const mermaid = window.mermaid;

const MARKDOWN_EXT = new Set(["md", "markdown", "mdown", "mkd"]);
const IMAGE_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "ico", "avif"]);
const PDF_EXT = new Set(["pdf"]);
const initialPath = boot.initialPath;
const initialFiles = boot.files;
const content = document.getElementById("content");
const status = document.getElementById("status");
const nav = document.getElementById("nav");
const toc = document.getElementById("toc");
const layout = document.getElementById("layout");
const finder = document.getElementById("finder");
const themeToggle = document.getElementById("theme-toggle");
const filesCollapse = document.getElementById("files-collapse");
const filesExpand = document.getElementById("files-expand");
const tocCollapse = document.getElementById("toc-collapse");
const tocExpand = document.getElementById("toc-expand");
const stylePicker = document.getElementById("style-picker");
const styleSelect = document.getElementById("style-select");
const pygmentsLink = document.getElementById("pygments-css");
let currentPath = initialPath;
let allFiles = initialFiles;
let mermaidId = 0;
let focusIndex = -1;
let tocObserver = null;
let brokenLinkToken = 0;
let tocCollapsedPref = false;
let appConfig = boot.config || {
  theme: "light",
  styles: { light: "default", dark: "nord" },
  available_styles: ["default", "nord"],
  sidebars: { files_collapsed: false, toc_collapsed: false },
};

if (!mermaid) {
  console.error("mermaid failed to load from local assets");
}

function currentTheme() {
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

function reloadPygmentsCss() {
  if (!pygmentsLink) return;
  const url = new URL(pygmentsLink.href, location.href);
  url.searchParams.set("t", String(Date.now()));
  pygmentsLink.href = url.pathname + url.search;
}

async function saveConfig(patch) {
  const res = await fetch("/__api/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error("Failed to save config");
  appConfig = await res.json();
  return appConfig;
}

function syncStyleSelect() {
  const theme = currentTheme();
  const selected = appConfig.styles?.[theme] || (theme === "dark" ? "nord" : "default");
  const styles = appConfig.available_styles || [];
  styleSelect.replaceChildren();
  for (const name of styles) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    if (name === selected) opt.selected = true;
    styleSelect.appendChild(opt);
  }
}

function applyTheme(theme, { persist = true } = {}) {
  document.documentElement.setAttribute("data-theme", theme);
  try { localStorage.setItem("markdown-serve-theme", theme); } catch (_) {}
  if (mermaid) {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "loose",
      theme: theme === "dark" ? "dark" : "neutral",
    });
  }
  themeToggle.setAttribute("aria-label", theme === "dark" ? "Switch to light theme" : "Switch to dark theme");
  themeToggle.title = theme === "dark" ? "Light theme" : "Dark theme";
  syncStyleSelect();
  if (persist) {
    saveConfig({ theme }).catch((err) => console.error(err));
  }
}

themeToggle.addEventListener("click", () => {
  const next = currentTheme() === "dark" ? "light" : "dark";
  applyTheme(next);
  if (currentPath && fileKind(currentPath) === "markdown") {
    load(currentPath, { line: lineFromLocation() });
  }
});

themeToggle.addEventListener("contextmenu", (e) => {
  e.preventDefault();
  const open = stylePicker.hidden;
  stylePicker.hidden = !open;
  if (open) styleSelect.focus();
});

styleSelect.addEventListener("change", async () => {
  const theme = currentTheme();
  const style = styleSelect.value;
  try {
    await saveConfig({ styles: { [theme]: style } });
    reloadPygmentsCss();
  } catch (err) {
    console.error(err);
    syncStyleSelect();
  }
});

applyTheme(appConfig.theme || currentTheme(), { persist: false });

function setFilesCollapsed(collapsed, { persist = true } = {}) {
  layout.classList.toggle("files-collapsed", collapsed);
  filesExpand.hidden = !collapsed;
  filesCollapse.setAttribute("aria-expanded", collapsed ? "false" : "true");
  if (persist) {
    const sidebars = { ...(appConfig.sidebars || {}), files_collapsed: collapsed };
    appConfig = { ...appConfig, sidebars };
    saveConfig({ sidebars: { files_collapsed: collapsed } }).catch((err) => console.error(err));
  }
  requestAnimationFrame(fitWideTables);
}

function syncTocExpandButton() {
  const hasToc = !layout.classList.contains("no-toc");
  const collapsed = layout.classList.contains("toc-collapsed");
  tocExpand.hidden = !(hasToc && collapsed);
  tocCollapse.setAttribute("aria-expanded", collapsed ? "false" : "true");
}

function setTocCollapsed(collapsed, { persist = true } = {}) {
  tocCollapsedPref = collapsed;
  layout.classList.toggle("toc-collapsed", collapsed);
  syncTocExpandButton();
  if (persist) {
    const sidebars = { ...(appConfig.sidebars || {}), toc_collapsed: collapsed };
    appConfig = { ...appConfig, sidebars };
    saveConfig({ sidebars: { toc_collapsed: collapsed } }).catch((err) => console.error(err));
  }
  requestAnimationFrame(fitWideTables);
}

filesCollapse.addEventListener("click", () => setFilesCollapsed(true));
filesExpand.addEventListener("click", () => setFilesCollapsed(false));
tocCollapse.addEventListener("click", () => setTocCollapsed(true));
tocExpand.addEventListener("click", () => setTocCollapsed(false));

const sidebarPrefs = appConfig.sidebars || {};
setFilesCollapsed(Boolean(sidebarPrefs.files_collapsed), { persist: false });
tocCollapsedPref = Boolean(sidebarPrefs.toc_collapsed);
setTocCollapsed(tocCollapsedPref, { persist: false });

function extOf(path) {
  const i = path.lastIndexOf(".");
  return i >= 0 ? path.slice(i + 1).toLowerCase() : "";
}

function fileKind(path) {
  const ext = extOf(path);
  if (MARKDOWN_EXT.has(ext)) return "markdown";
  if (PDF_EXT.has(ext)) return "pdf";
  if (IMAGE_EXT.has(ext)) return "image";
  return "other";
}

function encodePath(path) {
  return path.split("/").map(encodeURIComponent).join("/");
}

function basename(path) {
  const i = path.lastIndexOf("/");
  return i >= 0 ? path.slice(i + 1) : path;
}

function dirname(path) {
  const i = path.lastIndexOf("/");
  return i >= 0 ? path.slice(0, i) : "";
}

function fuzzyScore(query, candidate) {
  if (!query) return 1;
  if (query.startsWith("'")) {
    return exactScore(query.slice(1), candidate);
  }
  const q = query.toLowerCase();
  const name = basename(candidate).toLowerCase();
  const full = candidate.toLowerCase();
  let score = scoreSubsequence(q, name);
  if (score < 0) {
    score = scoreSubsequence(q, full);
    if (score >= 0) score *= 0.55;
  } else {
    score += 8;
  }
  return score;
}

function exactScore(query, candidate) {
  if (!query) return 1;
  const q = query.toLowerCase();
  const name = basename(candidate).toLowerCase();
  const full = candidate.toLowerCase();
  const nameIdx = name.indexOf(q);
  if (nameIdx >= 0) {
    let score = 1000 - nameIdx * 2;
    if (name === q) score += 200;
    else if (name.startsWith(q)) score += 80;
    return score;
  }
  const fullIdx = full.indexOf(q);
  if (fullIdx >= 0) return 400 - fullIdx;
  return -1;
}

function scoreSubsequence(query, text) {
  let qi = 0, score = 0, prev = -2, run = 0;
  for (let i = 0; i < text.length && qi < query.length; i++) {
    if (text[i] !== query[qi]) continue;
    run = i === prev + 1 ? run + 1 : 1;
    score += 1 + run * 3;
    if (i === 0 || "/-_ .".includes(text[i - 1])) score += 5;
    prev = i;
    qi++;
  }
  return qi === query.length ? score : -1;
}

let searchMode = "files";
let contentSearchToken = 0;
let contentSearchTimer = null;

function setSearchMode(mode) {
  searchMode = mode === "content" ? "content" : "files";
  const filesBtn = document.getElementById("search-mode-files");
  const contentBtn = document.getElementById("search-mode-content");
  filesBtn.classList.toggle("active", searchMode === "files");
  contentBtn.classList.toggle("active", searchMode === "content");
  filesBtn.setAttribute("aria-selected", searchMode === "files" ? "true" : "false");
  contentBtn.setAttribute("aria-selected", searchMode === "content" ? "true" : "false");
  finder.placeholder = searchMode === "content" ? "Search content…" : "Search files…";
  renderNav(allFiles, currentPath, finder.value);
}

document.getElementById("search-mode-files").addEventListener("click", () => setSearchMode("files"));
document.getElementById("search-mode-content").addEventListener("click", () => setSearchMode("content"));

function buildTree(files) {
  const root = { dirs: {}, files: [] };
  for (const path of files) {
    const parts = path.split("/");
    let node = root;
    for (let i = 0; i < parts.length - 1; i++) {
      const part = parts[i];
      if (!node.dirs[part]) node.dirs[part] = { dirs: {}, files: [] };
      node = node.dirs[part];
    }
    node.files.push({ name: parts[parts.length - 1], path });
  }
  return root;
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);
}

function linkHtml(path, active, { showPath = false, snippet = "", line = null } = {}) {
  const kind = fileKind(path);
  const name = basename(path);
  const activeClass = path === active ? " active" : "";
  const dir = dirname(path);
  const pathHint = showPath && dir
    ? '<span class="path-hint">' + escapeHtml(dir) + "</span>"
    : "";
  const lineAttr = line != null ? ' data-line="' + String(line) + '"' : "";
  const href = "/" + escapeHtml(path) + (line != null ? "?line=" + String(line) : "");
  const lineBadge = line != null
    ? '<span class="line-badge">L' + String(line) + "</span>"
    : "";
  const top = '<span class="hit-top">' +
    '<span class="name">' + escapeHtml(name) + "</span>" +
    pathHint +
    lineBadge +
    '<span class="ext">' + escapeHtml(extOf(path) || "file") + "</span>" +
    "</span>";
  const snip = snippet
    ? '<span class="search-snippet">' + escapeHtml(snippet) + "</span>"
    : "";
  return '<a href="' + href +
    '" class="nav-link kind-' + kind + activeClass +
    '" data-path="' + escapeHtml(path) + '"' +
    lineAttr +
    ' title="' + escapeHtml(path) + (line != null ? ":" + String(line) : "") + '">' +
    (snippet || line != null ? top + snip : (
      '<span class="name">' + escapeHtml(name) + "</span>" +
      pathHint +
      '<span class="ext">' + escapeHtml(extOf(path) || "file") + "</span>"
    )) +
    "</a>";
}

function renderNode(node, active, prefix) {
  const dirNames = Object.keys(node.dirs).sort((a, b) => a.localeCompare(b));
  const files = [...node.files].sort((a, b) => a.name.localeCompare(b.name));
  let html = '<ul class="tree-level">';
  for (const name of dirNames) {
    const childPrefix = prefix ? prefix + "/" + name : name;
    const open = !active || active === childPrefix || active.startsWith(childPrefix + "/");
    html += "<li><details" + (open ? " open" : "") + ">" +
      '<summary><span class="folder-name">' + escapeHtml(name) + "</span></summary>" +
      renderNode(node.dirs[name], active, childPrefix) +
      "</details></li>";
  }
  for (const file of files) {
    html += "<li>" + linkHtml(file.path, active) + "</li>";
  }
  html += "</ul>";
  return html;
}

function renderFileTree(files, active) {
  nav.innerHTML = renderNode(buildTree(files), active, "").replace(
    'class="tree-level"', 'class="tree"'
  );
}

async function renderContentSearch(files, active, query) {
  const token = ++contentSearchToken;
  const q = query.trim();
  if (!files.length) {
    nav.innerHTML = '<p class="empty">No matching files in this directory.</p>';
    return;
  }
  if (!q) {
    renderFileTree(files, active);
    return;
  }
  nav.innerHTML = '<p class="empty">Searching…</p>';
  try {
    const res = await fetch("/__api/search?" + new URLSearchParams({ q }));
    if (token !== contentSearchToken) return;
    if (!res.ok) throw new Error("search failed");
    const ranked = await res.json();
    if (token !== contentSearchToken) return;
    if (!ranked.length) {
      nav.innerHTML = '<p class="empty">No content matches “' + escapeHtml(q) + '”.</p>';
      return;
    }
    nav.innerHTML = '<ul class="flat-results content-results">' +
      ranked.map((x) => "<li>" + linkHtml(x.path, active, {
        showPath: true,
        snippet: x.snippet || "",
        line: x.line,
      }) + "</li>").join("") +
      "</ul>";
  } catch (_) {
    if (token !== contentSearchToken) return;
    nav.innerHTML = '<p class="empty">Content search failed.</p>';
  }
}

function scheduleContentSearch(files, active, query) {
  if (contentSearchTimer != null) clearTimeout(contentSearchTimer);
  const q = query.trim();
  if (!q) {
    contentSearchToken += 1;
    renderFileTree(files, active);
    return;
  }
  nav.innerHTML = '<p class="empty">Searching…</p>';
  contentSearchTimer = setTimeout(() => {
    contentSearchTimer = null;
    renderContentSearch(files, active, query);
  }, 150);
}

function renderNav(files, active, query = "") {
  allFiles = files;
  focusIndex = -1;
  if (searchMode === "content") {
    scheduleContentSearch(files, active, query);
    return;
  }
  if (contentSearchTimer != null) {
    clearTimeout(contentSearchTimer);
    contentSearchTimer = null;
  }
  const q = query.trim();
  if (!files.length) {
    nav.innerHTML = '<p class="empty">No matching files in this directory.</p>';
    return;
  }
  if (!q) {
    renderFileTree(files, active);
    return;
  }
  const ranked = files
    .map((path) => ({ path, score: fuzzyScore(q, path) }))
    .filter((x) => x.score >= 0)
    .sort((a, b) => b.score - a.score || a.path.localeCompare(b.path));
  if (!ranked.length) {
    nav.innerHTML = '<p class="empty">No files match “' + escapeHtml(q) + '”.</p>';
    return;
  }
  nav.innerHTML = '<ul class="flat-results">' +
    ranked.map((x) => "<li>" + linkHtml(x.path, active, { showPath: true }) + "</li>").join("") +
    "</ul>";
}

function visibleLinks() {
  return [...nav.querySelectorAll("a.nav-link")];
}

function setFocus(index) {
  const links = visibleLinks();
  links.forEach((a) => a.classList.remove("focused"));
  if (!links.length) { focusIndex = -1; return; }
  focusIndex = ((index % links.length) + links.length) % links.length;
  const el = links[focusIndex];
  el.classList.add("focused");
  el.scrollIntoView({ block: "nearest" });
}

async function renderDiagrams() {
  for (const node of [...content.querySelectorAll(".diagram-mermaid")]) {
    const source = node.querySelector(".diagram-source")?.textContent ?? "";
    if (!source.trim()) continue;
    const id = "mermaid-" + (++mermaidId);
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

let plantumlCache = new Map(); // source -> { svg, width, height }
let plantumlCachePath = null;

function snapshotPlantumlLayout() {
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

function preparePlantumlPlaceholders(snapshots) {
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

function fitWideTables() {
  if (content.classList.contains("asset-mode")) return;
  content.style.width = "";
  content.style.minWidth = "";
  const base = Math.min(52 * 16, content.parentElement.clientWidth);
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
  if (widest <= 0) {
    content.style.width = "min(52rem, 100%)";
    content.style.minWidth = "min(52rem, 100%)";
    return;
  }
  const style = getComputedStyle(content);
  const pad = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
  const border = parseFloat(style.borderLeftWidth) + parseFloat(style.borderRightWidth);
  const needed = Math.ceil(widest + pad + border);
  const width = Math.max(base, needed);
  content.style.width = width + "px";
  content.style.minWidth = width + "px";
}

function markActive(path) {
  nav.querySelectorAll(".nav-link").forEach((a) => {
    a.classList.toggle("active", a.dataset.path === path);
  });
  nav.querySelectorAll("details").forEach((d) => {
    if (d.querySelector(".nav-link.active")) d.open = true;
  });
}

function clearToc() {
  if (tocObserver) {
    tocObserver.disconnect();
    tocObserver = null;
  }
  toc.innerHTML = "";
  layout.classList.add("no-toc");
  syncTocExpandButton();
}

function buildNestedToc(headings) {
  const root = document.createElement("ol");
  root.className = "toc-list";
  const stack = [{ level: 0, list: root }];

  for (const heading of headings) {
    const level = Number(heading.tagName.slice(1));
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = "#" + heading.id;
    a.textContent = heading.textContent.replace(/\s*¶\s*$/, "").trim() || heading.id;
    a.addEventListener("click", (e) => {
      e.preventDefault();
      heading.scrollIntoView({ behavior: "smooth", block: "start" });
      history.replaceState(null, "", "#" + heading.id);
      setTocActive(heading.id);
    });
    li.appendChild(a);

    while (stack.length > 1 && stack[stack.length - 1].level >= level) {
      stack.pop();
    }

    const parent = stack[stack.length - 1];
    parent.list.appendChild(li);

    const nested = document.createElement("ol");
    nested.className = "toc-list";
    li.appendChild(nested);
    stack.push({ level, list: nested });
  }

  root.querySelectorAll("ol").forEach((ol) => {
    if (!ol.children.length) ol.remove();
  });
  return root;
}

function updateToc() {
  clearToc();
  if (content.classList.contains("asset-mode")) return;

  const headings = [...content.querySelectorAll("h1[id], h2[id], h3[id], h4[id]")];
  if (!headings.length) return;

  layout.classList.remove("no-toc");
  layout.classList.toggle("toc-collapsed", tocCollapsedPref);
  syncTocExpandButton();
  toc.appendChild(buildNestedToc(headings));

  tocObserver = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (visible[0]?.target?.id) setTocActive(visible[0].target.id);
    },
    { rootMargin: "-10% 0px -70% 0px", threshold: [0, 1] },
  );
  for (const heading of headings) tocObserver.observe(heading);
  setTocActive(headings[0].id);
  requestAnimationFrame(fitWideTables);
}

function setTocActive(id) {
  toc.querySelectorAll("a").forEach((a) => {
    a.classList.toggle("active", a.getAttribute("href") === "#" + id);
  });
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
  const token = ++brokenLinkToken;
  const anchors = [...content.querySelectorAll("a[href]")];
  await Promise.all(anchors.map(async (a) => {
    if (a.classList.contains("headerlink")) return;
    const target = resolveLocalTarget(a.getAttribute("href"), fromPath);
    if (!target) return;
    try {
      const res = await fetch("/__api/exists/" + encodePath(target));
      if (token !== brokenLinkToken) return;
      if (!res.ok) return;
      const data = await res.json();
      if (token !== brokenLinkToken) return;
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

async function load(path, { line = null } = {}) {
  if (!path) {
    content.classList.remove("asset-mode");
    content.innerHTML = '<p class="empty">Select a file.</p>';
    clearToc();
    return;
  }
  const previousPath = currentPath;
  const preserveScroll = previousPath === path && (line == null || line <= 0);
  const kind = fileKind(path);
  currentPath = path;
  document.title = path + " — markdown-serve";
  const lineQuery = line != null && line > 0 ? "?line=" + String(line) : "";
  history.replaceState(null, "", "/" + encodePath(path) + lineQuery);
  markActive(path);

  if (kind === "image") {
    content.classList.add("asset-mode");
    content.style.width = "";
    content.style.minWidth = "";
    content.innerHTML = '<img class="asset-preview" src="/__file/' +
      encodePath(path) + '" alt="' + escapeHtml(basename(path)) + '">';
    clearToc();
    return;
  }
  if (kind === "pdf") {
    content.classList.add("asset-mode");
    content.style.width = "";
    content.style.minWidth = "";
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
    return;
  }
  const data = await res.json();
  if (plantumlCachePath !== path) {
    plantumlCache = new Map();
    plantumlCachePath = path;
  }
  const scrollState = preserveScroll ? captureScrollAnchor() : null;
  const plantumlSnapshots = snapshotPlantumlLayout();
  content.innerHTML = data.html;
  preparePlantumlPlaceholders(plantumlSnapshots);
  updateToc();
  await renderDiagrams();
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

function restoreScrollAnchor(state) {
  if (!state) return;
  const scroller = document.scrollingElement || document.documentElement;
  const anchor = state.anchor;
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
  scroller.scrollTop = state.scrollY;
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

function lineFromLocation() {
  try {
    const sp = new URL(location.href).searchParams.get("line");
    if (sp && /^\d+$/.test(sp)) return Number(sp);
  } catch (_) {}
  const m = location.hash.match(/^#L(\d+)$/i);
  return m ? Number(m[1]) : null;
}

window.addEventListener("resize", fitWideTables);

nav.addEventListener("click", (e) => {
  const a = e.target.closest("a.nav-link");
  if (!a) return;
  e.preventDefault();
  const line = a.dataset.line ? Number(a.dataset.line) : null;
  load(a.dataset.path, { line: Number.isFinite(line) && line > 0 ? line : null });
});

finder.addEventListener("input", () => {
  renderNav(allFiles, currentPath, finder.value);
});

finder.addEventListener("keydown", (e) => {
  if (e.key === "Tab" && !e.altKey && !e.metaKey && !e.ctrlKey) {
    e.preventDefault();
    setSearchMode(searchMode === "files" ? "content" : "files");
    return;
  }
  if (e.key === "ArrowDown") {
    e.preventDefault();
    setFocus(focusIndex < 0 ? 0 : focusIndex + 1);
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    setFocus(focusIndex < 0 ? visibleLinks().length - 1 : focusIndex - 1);
  } else if (e.key === "Enter") {
    const links = visibleLinks();
    const target = focusIndex >= 0 ? links[focusIndex] : links[0];
    if (target) {
      e.preventDefault();
      const line = target.dataset.line ? Number(target.dataset.line) : null;
      load(target.dataset.path, { line: Number.isFinite(line) && line > 0 ? line : null });
    }
  } else if (e.key === "Escape") {
    if (finder.value) {
      finder.value = "";
      renderNav(allFiles, currentPath, "");
    } else {
      finder.blur();
    }
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "/" && document.activeElement !== finder &&
      document.activeElement?.tagName !== "INPUT" &&
      document.activeElement?.tagName !== "TEXTAREA") {
    e.preventDefault();
    finder.focus();
    finder.select();
  }
});

const MAX_RECONNECT_ATTEMPTS = 3;
let reconnectAttempts = 0;
let reconnectTimer = null;
let activeSocket = null;

function clearReconnectTimer() {
  if (reconnectTimer != null) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
}

function showDisconnected() {
  clearReconnectTimer();
  status.classList.remove("live");
  status.classList.add("offline");
  status.replaceChildren();
  status.append("disconnected");
  const btn = document.createElement("button");
  btn.type = "button";
  btn.id = "reconnect-btn";
  btn.className = "reconnect-btn";
  btn.textContent = "Reconnect";
  btn.addEventListener("click", () => {
    reconnectAttempts = 0;
    connect();
  });
  status.appendChild(btn);
}

function connect() {
  clearReconnectTimer();
  if (activeSocket) {
    activeSocket.onopen = null;
    activeSocket.onclose = null;
    activeSocket.onmessage = null;
    activeSocket.onerror = null;
    try { activeSocket.close(); } catch (_) {}
    activeSocket = null;
  }

  status.classList.remove("live", "offline");
  status.textContent = reconnectAttempts > 0
    ? `reconnecting (${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})…`
    : "connecting…";

  const proto = location.protocol === "https:" ? "wss" : "ws";
  let ws;
  try {
    ws = new WebSocket(proto + "://" + location.host + "/__ws");
  } catch (_) {
    reconnectAttempts += 1;
    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      showDisconnected();
      return;
    }
    reconnectTimer = setTimeout(connect, 800);
    return;
  }
  activeSocket = ws;

  ws.onopen = () => {
    reconnectAttempts = 0;
    status.classList.remove("offline");
    status.classList.add("live");
    status.textContent = "live";
  };

  ws.onclose = () => {
    if (activeSocket === ws) activeSocket = null;
    status.classList.remove("live");
    reconnectAttempts += 1;
    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      showDisconnected();
      return;
    }
    status.classList.remove("offline");
    status.textContent = `reconnecting (${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})…`;
    reconnectTimer = setTimeout(connect, 800);
  };

  ws.onmessage = async (ev) => {
    const changed = ev.data;
    try {
      const res = await fetch("/__api/files");
      const files = await res.json();
      renderNav(files, currentPath, finder.value);
      if (!currentPath && files.length) currentPath = files[0];
      if (currentPath && files.includes(currentPath)) await load(currentPath);
      else if (files.includes(changed)) await load(changed);
    } catch (_) {
      if (currentPath) await load(currentPath);
    }
  };
}

renderNav(initialFiles, initialPath);
load(initialPath, { line: lineFromLocation() });
connect();
