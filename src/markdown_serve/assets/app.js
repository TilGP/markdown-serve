import { initialFiles, initialPath, state } from "./js/state.js";
import { fileKind, isRenderedKind, lineFromLocation } from "./js/utils.js";
import { initTheme } from "./js/theme.js";
import { initLayout } from "./js/layout.js";
import { fitWideTables } from "./js/diagrams.js";
import { initNav, renderNav } from "./js/nav.js";
import { initPrint, load } from "./js/content.js";
import { connect } from "./js/live.js";

initTheme({
  onThemeToggle: () => {
    // Re-render so Mermaid picks up the new theme (markdown and diagram files).
    if (state.currentPath && isRenderedKind(fileKind(state.currentPath))) {
      load(state.currentPath, { line: lineFromLocation() });
    }
  },
});
initLayout();
initPrint();
initNav({ load });

window.addEventListener("resize", fitWideTables);

renderNav(initialFiles, initialPath);
load(initialPath, { line: lineFromLocation() });
connect();
