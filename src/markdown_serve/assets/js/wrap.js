import {
  textWrap, textWidth, tableWrap, tableWidth,
} from "./dom.js";
import { state } from "./state.js";
import { saveConfig } from "./theme.js";
import { fitWideTables } from "./diagrams.js";

const MIN_WIDTH = 20;
const MAX_WIDTH = 300;

// Mirrors wrap_css_vars() in config.py, which injects the same values at page load.
function wrapCssVars({ text, tables }) {
  return {
    "--text-width": `${text.width}ch`,
    "--text-max-width": text.wrap ? `${text.width}ch` : "none",
    "--table-cell-max-width": tables.wrap ? `${tables.width}ch` : "none",
    "--table-cell-white-space": tables.wrap ? "normal" : "nowrap",
  };
}

function syncControls() {
  const { text, tables } = state.appConfig;
  textWrap.checked = text.wrap;
  textWidth.value = String(text.width);
  textWidth.disabled = !text.wrap;
  tableWrap.checked = tables.wrap;
  tableWidth.value = String(tables.width);
  tableWidth.disabled = !tables.wrap;
}

export function applyWrap() {
  const vars = wrapCssVars(state.appConfig);
  for (const [name, value] of Object.entries(vars)) {
    document.documentElement.style.setProperty(name, value);
  }
  syncControls();
  requestAnimationFrame(fitWideTables);
}

function bind(key, wrapEl, widthEl) {
  const update = async () => {
    const parsed = Number.parseInt(widthEl.value, 10);
    const width = Number.isFinite(parsed)
      ? Math.min(Math.max(parsed, MIN_WIDTH), MAX_WIDTH)
      : state.appConfig[key].width;
    const next = { wrap: wrapEl.checked, width };
    state.appConfig = { ...state.appConfig, [key]: next };
    applyWrap();
    try {
      await saveConfig({ [key]: next });
    } catch (err) {
      console.error(err);
    }
    applyWrap();
  };
  wrapEl.addEventListener("change", update);
  widthEl.addEventListener("change", update);
}

export function initWrap() {
  bind("text", textWrap, textWidth);
  bind("tables", tableWrap, tableWidth);
  applyWrap();
}
