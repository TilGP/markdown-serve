import { finder } from "./dom.js";
import { state } from "./state.js";
import { fileKind } from "./utils.js";
import { renderNav } from "./nav.js";
import { load } from "./content.js";
import { saveConfig } from "./theme.js";

const panel = document.getElementById("codedoc-panel");
const toggle = document.getElementById("codedoc-toggle");
const tools = document.getElementById("codedoc-tools");
const summary = document.getElementById("codedoc-summary");
const buildBtn = document.getElementById("codedoc-build");
const updateBtn = document.getElementById("codedoc-update");
const cancelBtn = document.getElementById("codedoc-cancel");
const progress = document.getElementById("codedoc-progress");
const progressText = document.getElementById("codedoc-progress-text");
const errors = document.getElementById("codedoc-errors");
const errorCount = document.getElementById("codedoc-error-count");
const errorList = document.getElementById("codedoc-error-list");
const sidebarBox = document.getElementById("codedoc-sidebar");

let pollTimer = null;

function escapeText(value) {
  return String(value ?? "");
}

function renderStatus(data) {
  tools.replaceChildren();
  const groups = data.tools || {};
  for (const [language, status] of Object.entries(groups)) {
    const checks = status.checks || [];
    if (!checks.length) {
      const item = document.createElement("li");
      item.textContent = `${language}: ${status.available ? "ready" : "unavailable"}`;
      tools.appendChild(item);
    }
    for (const check of checks) {
      const item = document.createElement("li");
      const mark = document.createElement("span");
      mark.className = check.ok ? "ok" : "missing";
      mark.textContent = check.ok ? "ok" : "missing";
      item.append(mark, ` ${language} ${check.name}: ${escapeText(check.hint)}`);
      tools.appendChild(item);
    }
  }
  const manifest = data.manifest;
  if (manifest && manifest.built_at) {
    const parts = Object.entries(manifest.languages || {}).map(
      ([language, info]) => `${language}: ${info.files} files, ${info.symbols} symbols`,
    );
    summary.textContent = `Last build ${manifest.built_at}${parts.length ? " · " + parts.join(" · ") : ""}`;
  } else {
    summary.textContent = "No cache yet.";
  }

  const prog = data.progress || {};
  const total = Number(prog.total) || 0;
  const done = Number(prog.done) || 0;
  progress.max = total > 0 ? total : 1;
  progress.value = total > 0 ? done : (data.running ? 0 : 0);
  if (data.running) {
    progressText.textContent = total
      ? `${prog.language || ""} · ${done} / ${total} · ${prog.current || ""}`.replace(/^ · | · $/g, "")
      : `${prog.language || ""} ${prog.phase || "working"}…`;
  } else {
    progressText.textContent = prog.phase && prog.phase !== "idle" ? prog.phase : "";
  }
  buildBtn.disabled = data.running;
  updateBtn.disabled = data.running;
  cancelBtn.disabled = !data.running;

  const list = prog.errors || [];
  errors.hidden = list.length === 0;
  errorCount.textContent = `${list.length} error${list.length === 1 ? "" : "s"}`;
  errorList.replaceChildren();
  for (const error of list) {
    const item = document.createElement("li");
    item.textContent = error;
    errorList.appendChild(item);
  }
}

async function fetchStatus() {
  const res = await fetch("/__api/codedoc/status");
  if (!res.ok) throw new Error("status failed");
  const data = await res.json();
  renderStatus(data);
  return data;
}

function stopPoll() {
  if (pollTimer != null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function startPoll() {
  if (pollTimer != null) return;
  pollTimer = setInterval(async () => {
    try {
      const data = await fetchStatus();
      if (!data.running) {
        stopPoll();
        await refreshAfterCodeDocBuild();
      }
    } catch (_) {
      stopPoll();
    }
  }, 500);
}

export async function refreshAfterCodeDocBuild() {
  try {
    const res = await fetch("/__api/files");
    const files = res.ok ? await res.json() : state.projectFiles;
    if (state.appConfig.codedoc?.show_in_sidebar) {
      const code = await fetch("/__api/codedoc/files");
      state.codeDocFiles = code.ok ? await code.json() : [];
    }
    renderNav(files, state.currentPath, finder.value);
    if (state.currentPath && fileKind(state.currentPath) === "code") {
      await load(state.currentPath);
    }
  } catch (_) {
    if (state.currentPath) await load(state.currentPath);
  }
}

async function startBuild(force) {
  const res = await fetch("/__api/codedoc/build", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ force }),
  });
  if (res.status === 409) {
    startPoll();
    return;
  }
  if (!res.ok) {
    progressText.textContent = "Build failed to start.";
    return;
  }
  renderStatus(await res.json());
  startPoll();
}

export function initCodedoc() {
  if (!panel || !toggle) return;
  sidebarBox.checked = !!state.appConfig.codedoc?.show_in_sidebar;

  toggle.addEventListener("click", async () => {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) {
      try {
        const data = await fetchStatus();
        if (data.running) startPoll();
      } catch (_) {
        summary.textContent = "Could not read code-doc status.";
      }
    }
  });

  document.addEventListener("click", (event) => {
    if (panel.hidden) return;
    if (panel.contains(event.target) || toggle.contains(event.target)) return;
    panel.hidden = true;
  });

  buildBtn.addEventListener("click", () => startBuild(true));
  updateBtn.addEventListener("click", () => startBuild(false));
  cancelBtn.addEventListener("click", async () => {
    await fetch("/__api/codedoc/cancel", { method: "POST" });
  });

  sidebarBox.addEventListener("change", async () => {
    const show = sidebarBox.checked;
    try {
      await saveConfig({ codedoc: { show_in_sidebar: show } });
    } catch (err) {
      console.error(err);
      sidebarBox.checked = !show;
      return;
    }
    if (show) {
      try {
        const res = await fetch("/__api/codedoc/files");
        state.codeDocFiles = res.ok ? await res.json() : [];
      } catch (_) {
        state.codeDocFiles = [];
      }
    }
    renderNav(state.projectFiles, state.currentPath, finder.value);
  });

  if (state.appConfig.codedoc?.show_in_sidebar) {
    fetch("/__api/codedoc/files")
      .then((res) => (res.ok ? res.json() : []))
      .then((files) => {
        state.codeDocFiles = files;
        renderNav(state.projectFiles, state.currentPath, finder.value);
      })
      .catch(() => {});
  }
}
