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
const finder = document.getElementById("finder");
const themeToggle = document.getElementById("theme-toggle");
const stylePicker = document.getElementById("style-picker");
const styleSelect = document.getElementById("style-select");
const pygmentsLink = document.getElementById("pygments-css");
let currentPath = initialPath;
let allFiles = initialFiles;
let mermaidId = 0;
let focusIndex = -1;
let appConfig = boot.config || {
  theme: "light",
  styles: { light: "default", dark: "nord" },
  available_styles: ["default", "nord"],
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
  if (currentPath && fileKind(currentPath) === "markdown") load(currentPath);
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

function linkHtml(path, active, { showPath = false } = {}) {
  const kind = fileKind(path);
  const name = basename(path);
  const activeClass = path === active ? " active" : "";
  const dir = dirname(path);
  const pathHint = showPath && dir
    ? '<span class="path-hint">' + escapeHtml(dir) + "</span>"
    : "";
  return '<a href="/' + escapeHtml(path) +
    '" class="nav-link kind-' + kind + activeClass +
    '" data-path="' + escapeHtml(path) +
    '" title="' + escapeHtml(path) + '">' +
    '<span class="name">' + escapeHtml(name) + "</span>" +
    pathHint +
    '<span class="ext">' + escapeHtml(extOf(path) || "file") + "</span></a>";
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

function renderNav(files, active, query = "") {
  allFiles = files;
  focusIndex = -1;
  const q = query.trim();
  if (!files.length) {
    nav.innerHTML = '<p class="empty">No matching files in this directory.</p>';
    return;
  }
  if (!q) {
    nav.innerHTML = renderNode(buildTree(files), active, "").replace(
      'class="tree-level"', 'class="tree"'
    );
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
    return {
      source,
      width: Math.max(0, Math.round(rect.width)),
      height: Math.max(0, Math.round(rect.height)),
      svg: svg ? svg.outerHTML : (plantumlCache.get(source)?.svg ?? ""),
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
  node.innerHTML = sourceHtml +
    `<div class="diagram-skeleton" style="width:${w};max-width:100%;height:${h};min-height:${h}" aria-hidden="true"></div>`;
}

function setPlantumlSvg(node, svg) {
  const sourceHtml = plantumlSourceHtml(node);
  node.innerHTML = sourceHtml + svg;
  const rendered = node.querySelector("svg") || node;
  const rect = rendered.getBoundingClientRect();
  const source = node.querySelector(".diagram-source")?.textContent ?? "";
  if (source.trim()) {
    plantumlCache.set(source, {
      svg,
      width: Math.max(0, Math.round(rect.width)),
      height: Math.max(0, Math.round(rect.height)),
    });
  }
}

function preparePlantumlPlaceholders(snapshots) {
  const nodes = [...content.querySelectorAll(".diagram-plantuml")];
  nodes.forEach((node, index) => {
    const source = node.querySelector(".diagram-source")?.textContent ?? "";
    if (!source.trim()) return;

    const cached = plantumlCache.get(source);
    if (cached?.svg) {
      setPlantumlSvg(node, cached.svg);
      return;
    }

    const prev = snapshots[index];
    const width = prev?.width || 0;
    const height = prev?.height || 0;
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
      setPlantumlSvg(node, text);
      fitWideTables();
    } catch (err) {
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

async function load(path) {
  if (!path) {
    content.classList.remove("asset-mode");
    content.innerHTML = '<p class="empty">Select a file.</p>';
    return;
  }
  const kind = fileKind(path);
  currentPath = path;
  document.title = path + " — markdown-serve";
  history.replaceState(null, "", "/" + encodePath(path));
  markActive(path);

  if (kind === "image") {
    content.classList.add("asset-mode");
    content.style.width = "";
    content.style.minWidth = "";
    content.innerHTML = '<img class="asset-preview" src="/__file/' +
      encodePath(path) + '" alt="' + escapeHtml(basename(path)) + '">';
    return;
  }
  if (kind === "pdf") {
    content.classList.add("asset-mode");
    content.style.width = "";
    content.style.minWidth = "";
    content.innerHTML = '<iframe class="pdf-preview" title="' +
      escapeHtml(basename(path)) + '" src="/__file/' + encodePath(path) + '"></iframe>';
    return;
  }

  content.classList.remove("asset-mode");
  const res = await fetch("/__api/render/" + encodePath(path));
  if (!res.ok) {
    content.innerHTML = '<p class="empty">Failed to load ' + escapeHtml(path) + "</p>";
    return;
  }
  const data = await res.json();
  if (plantumlCachePath !== path) {
    plantumlCache = new Map();
    plantumlCachePath = path;
  }
  const plantumlSnapshots = snapshotPlantumlLayout();
  content.innerHTML = data.html;
  preparePlantumlPlaceholders(plantumlSnapshots);
  await renderDiagrams();
  fitWideTables();
}

window.addEventListener("resize", fitWideTables);

nav.addEventListener("click", (e) => {
  const a = e.target.closest("a.nav-link");
  if (!a) return;
  e.preventDefault();
  load(a.dataset.path);
});

finder.addEventListener("input", () => {
  renderNav(allFiles, currentPath, finder.value);
});

finder.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") {
    e.preventDefault();
    setFocus(focusIndex < 0 ? 0 : focusIndex + 1);
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    setFocus(focusIndex < 0 ? visibleLinks().length - 1 : focusIndex - 1);
  } else if (e.key === "Enter") {
    const links = visibleLinks();
    const target = focusIndex >= 0 ? links[focusIndex] : links[0];
    if (target) { e.preventDefault(); load(target.dataset.path); }
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
load(initialPath);
connect();
