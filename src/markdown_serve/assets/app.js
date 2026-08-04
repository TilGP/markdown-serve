import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
import plantumlEncoder from "https://cdn.jsdelivr.net/npm/plantuml-encoder@1.4.0/+esm";

const boot = JSON.parse(document.getElementById("markdown-serve-boot").textContent);

const PLANTUML_SERVER = "https://www.plantuml.com/plantuml/svg/";
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
let currentPath = initialPath;
let allFiles = initialFiles;
let mermaidId = 0;
let focusIndex = -1;

function currentTheme() {
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try { localStorage.setItem("markdown-serve-theme", theme); } catch (_) {}
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "loose",
    theme: theme === "dark" ? "dark" : "neutral",
  });
  themeToggle.setAttribute("aria-label", theme === "dark" ? "Switch to light theme" : "Switch to dark theme");
  themeToggle.title = theme === "dark" ? "Light theme" : "Dark theme";
}

themeToggle.addEventListener("click", () => {
  const next = currentTheme() === "dark" ? "light" : "dark";
  applyTheme(next);
  if (currentPath && fileKind(currentPath) === "markdown") load(currentPath);
});

applyTheme(currentTheme());

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
  for (const node of content.querySelectorAll(".diagram-plantuml")) {
    const source = node.querySelector(".diagram-source")?.textContent ?? "";
    if (!source.trim()) continue;
    const img = document.createElement("img");
    img.alt = "PlantUML diagram";
    img.src = PLANTUML_SERVER + plantumlEncoder.encode(source);
    img.onerror = () => {
      node.innerHTML = '<div class="diagram-error">Failed to render PlantUML diagram. ' +
        "Check syntax or plantuml.com availability.</div>";
    };
    node.replaceChildren(img);
  }
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
  content.innerHTML = data.html;
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

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(proto + "://" + location.host + "/__ws");
  ws.onopen = () => {
    status.textContent = "live";
    status.classList.add("live");
  };
  ws.onclose = () => {
    status.textContent = "reconnecting…";
    status.classList.remove("live");
    setTimeout(connect, 800);
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
