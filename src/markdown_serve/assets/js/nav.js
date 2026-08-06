import { nav, finder } from "./dom.js";
import { state } from "./state.js";
import {
  basename, dirname, escapeHtml, extOf, fileKind, fuzzyScore,
} from "./utils.js";

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
  const token = ++state.contentSearchToken;
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
    if (token !== state.contentSearchToken) return;
    if (!res.ok) throw new Error("search failed");
    const ranked = await res.json();
    if (token !== state.contentSearchToken) return;
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
    if (token !== state.contentSearchToken) return;
    nav.innerHTML = '<p class="empty">Content search failed.</p>';
  }
}

function scheduleContentSearch(files, active, query) {
  if (state.contentSearchTimer != null) clearTimeout(state.contentSearchTimer);
  const q = query.trim();
  if (!q) {
    state.contentSearchToken += 1;
    renderFileTree(files, active);
    return;
  }
  nav.innerHTML = '<p class="empty">Searching…</p>';
  state.contentSearchTimer = setTimeout(() => {
    state.contentSearchTimer = null;
    renderContentSearch(files, active, query);
  }, 150);
}

export function renderNav(files, active, query = "") {
  state.allFiles = files;
  state.focusIndex = -1;
  if (state.searchMode === "content") {
    scheduleContentSearch(files, active, query);
    return;
  }
  if (state.contentSearchTimer != null) {
    clearTimeout(state.contentSearchTimer);
    state.contentSearchTimer = null;
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

export function markActive(path) {
  nav.querySelectorAll(".nav-link").forEach((a) => {
    a.classList.toggle("active", a.dataset.path === path);
  });
  nav.querySelectorAll("details").forEach((d) => {
    if (d.querySelector(".nav-link.active")) d.open = true;
  });
}

function visibleLinks() {
  return [...nav.querySelectorAll("a.nav-link")];
}

function setFocus(index) {
  const links = visibleLinks();
  links.forEach((a) => a.classList.remove("focused"));
  if (!links.length) { state.focusIndex = -1; return; }
  state.focusIndex = ((index % links.length) + links.length) % links.length;
  const el = links[state.focusIndex];
  el.classList.add("focused");
  el.scrollIntoView({ block: "nearest" });
}

export function setSearchMode(mode) {
  state.searchMode = mode === "content" ? "content" : "files";
  const filesBtn = document.getElementById("search-mode-files");
  const contentBtn = document.getElementById("search-mode-content");
  filesBtn.classList.toggle("active", state.searchMode === "files");
  contentBtn.classList.toggle("active", state.searchMode === "content");
  filesBtn.setAttribute("aria-selected", state.searchMode === "files" ? "true" : "false");
  contentBtn.setAttribute("aria-selected", state.searchMode === "content" ? "true" : "false");
  finder.placeholder = state.searchMode === "content" ? "Search content…" : "Search files…";
  renderNav(state.allFiles, state.currentPath, finder.value);
}

export function initNav({ load } = {}) {
  document.getElementById("search-mode-files").addEventListener("click", () => setSearchMode("files"));
  document.getElementById("search-mode-content").addEventListener("click", () => setSearchMode("content"));

  nav.addEventListener("click", (e) => {
    const a = e.target.closest("a.nav-link");
    if (!a) return;
    e.preventDefault();
    const line = a.dataset.line ? Number(a.dataset.line) : null;
    load(a.dataset.path, { line: Number.isFinite(line) && line > 0 ? line : null });
  });

  finder.addEventListener("input", () => {
    renderNav(state.allFiles, state.currentPath, finder.value);
  });

  finder.addEventListener("keydown", (e) => {
    if (e.key === "Tab" && !e.altKey && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      setSearchMode(state.searchMode === "files" ? "content" : "files");
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setFocus(state.focusIndex < 0 ? 0 : state.focusIndex + 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setFocus(state.focusIndex < 0 ? visibleLinks().length - 1 : state.focusIndex - 1);
    } else if (e.key === "Enter") {
      const links = visibleLinks();
      const target = state.focusIndex >= 0 ? links[state.focusIndex] : links[0];
      if (target) {
        e.preventDefault();
        const line = target.dataset.line ? Number(target.dataset.line) : null;
        load(target.dataset.path, { line: Number.isFinite(line) && line > 0 ? line : null });
      }
    } else if (e.key === "Escape") {
      if (finder.value) {
        finder.value = "";
        renderNav(state.allFiles, state.currentPath, "");
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
}
