import {
  themeToggle, stylePicker, styleSelect, pygmentsLink,
} from "./dom.js";
import { state } from "./state.js";

export const mermaid = window.mermaid;

if (!mermaid) {
  console.error("mermaid failed to load from local assets");
}

export function currentTheme() {
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

export function reloadPygmentsCss() {
  if (!pygmentsLink) return;
  const url = new URL(pygmentsLink.href, location.href);
  url.searchParams.set("t", String(Date.now()));
  pygmentsLink.href = url.pathname + url.search;
}

export async function saveConfig(patch) {
  const res = await fetch("/__api/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error("Failed to save config");
  state.appConfig = await res.json();
  return state.appConfig;
}

export function syncStyleSelect() {
  const theme = currentTheme();
  const selected = state.appConfig.styles?.[theme] || (theme === "dark" ? "nord" : "default");
  const styles = state.appConfig.available_styles || [];
  styleSelect.replaceChildren();
  for (const name of styles) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    if (name === selected) opt.selected = true;
    styleSelect.appendChild(opt);
  }
}

export function applyTheme(theme, { persist = true } = {}) {
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

export function initTheme({ onThemeToggle } = {}) {
  themeToggle.addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    applyTheme(next);
    onThemeToggle?.();
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

  applyTheme(state.appConfig.theme || currentTheme(), { persist: false });
}
