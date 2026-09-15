const boot = JSON.parse(document.getElementById("markdown-serve-boot").textContent);

export const initialPath = boot.initialPath;
export const initialFiles = boot.files;

export const state = {
  currentPath: initialPath,
  allFiles: initialFiles,
  mermaidId: 0,
  focusIndex: -1,
  expandedDirs: new Set(),
  collapsedDirs: new Set(),
  revealedPath: null,
  tocObserver: null,
  brokenLinkToken: 0,
  tocCollapsedPref: false,
  searchMode: "files",
  contentSearchToken: 0,
  contentSearchTimer: null,
  appConfig: boot.config || {
    theme: "light",
    styles: { light: "default", dark: "nord" },
    available_styles: ["default", "nord"],
    sidebars: { files_collapsed: false, toc_collapsed: false },
    text: { wrap: true, width: 90 },
    tables: { wrap: true, width: 80 },
  },
};
