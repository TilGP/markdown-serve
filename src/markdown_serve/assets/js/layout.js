import {
  layout, filesCollapse, filesExpand, tocCollapse, tocExpand,
} from "./dom.js";
import { state } from "./state.js";
import { saveConfig } from "./theme.js";
import { fitWideTables } from "./diagrams.js";

export function syncTocExpandButton() {
  const hasToc = !layout.classList.contains("no-toc");
  const collapsed = layout.classList.contains("toc-collapsed");
  tocExpand.hidden = !(hasToc && collapsed);
  tocCollapse.setAttribute("aria-expanded", collapsed ? "false" : "true");
}

export function setFilesCollapsed(collapsed, { persist = true } = {}) {
  layout.classList.toggle("files-collapsed", collapsed);
  filesExpand.hidden = !collapsed;
  filesCollapse.setAttribute("aria-expanded", collapsed ? "false" : "true");
  if (persist) {
    const sidebars = { ...(state.appConfig.sidebars || {}), files_collapsed: collapsed };
    state.appConfig = { ...state.appConfig, sidebars };
    saveConfig({ sidebars: { files_collapsed: collapsed } }).catch((err) => console.error(err));
  }
  requestAnimationFrame(fitWideTables);
}

export function setTocCollapsed(collapsed, { persist = true } = {}) {
  state.tocCollapsedPref = collapsed;
  layout.classList.toggle("toc-collapsed", collapsed);
  syncTocExpandButton();
  if (persist) {
    const sidebars = { ...(state.appConfig.sidebars || {}), toc_collapsed: collapsed };
    state.appConfig = { ...state.appConfig, sidebars };
    saveConfig({ sidebars: { toc_collapsed: collapsed } }).catch((err) => console.error(err));
  }
  requestAnimationFrame(fitWideTables);
}

export function initLayout() {
  filesCollapse.addEventListener("click", () => setFilesCollapsed(true));
  filesExpand.addEventListener("click", () => setFilesCollapsed(false));
  tocCollapse.addEventListener("click", () => setTocCollapsed(true));
  tocExpand.addEventListener("click", () => setTocCollapsed(false));

  const sidebarPrefs = state.appConfig.sidebars || {};
  setFilesCollapsed(Boolean(sidebarPrefs.files_collapsed), { persist: false });
  state.tocCollapsedPref = Boolean(sidebarPrefs.toc_collapsed);
  setTocCollapsed(state.tocCollapsedPref, { persist: false });
}
