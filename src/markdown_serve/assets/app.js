import { initialFiles, initialPath, state } from "./js/state.js";
import { fileKind, lineFromLocation } from "./js/utils.js";
import { initTheme } from "./js/theme.js";
import { initLayout } from "./js/layout.js";
import { fitWideTables } from "./js/diagrams.js";
import { initNav, renderNav } from "./js/nav.js";
import { initPrint, load } from "./js/content.js";
import { connect } from "./js/live.js";

initTheme({
  onThemeToggle: () => {
    if (state.currentPath && fileKind(state.currentPath) === "markdown") {
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
