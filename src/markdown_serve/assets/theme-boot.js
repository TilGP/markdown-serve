(function () {
  try {
    var t = localStorage.getItem("markdown-serve-theme");
    if (t === "dark" || t === "light") document.documentElement.setAttribute("data-theme", t);
    else if (window.matchMedia("(prefers-color-scheme: dark)").matches)
      document.documentElement.setAttribute("data-theme", "dark");
    else document.documentElement.setAttribute("data-theme", "light");
  } catch (_) {
    document.documentElement.setAttribute("data-theme", "light");
  }
})();
