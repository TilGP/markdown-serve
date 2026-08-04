(function () {
  try {
    var el = document.documentElement;
    var attr = el.getAttribute("data-theme");
    if (attr === "dark" || attr === "light") {
      try { localStorage.setItem("markdown-serve-theme", attr); } catch (_) {}
      return;
    }
    var t = localStorage.getItem("markdown-serve-theme");
    if (t === "dark" || t === "light") el.setAttribute("data-theme", t);
    else if (window.matchMedia("(prefers-color-scheme: dark)").matches)
      el.setAttribute("data-theme", "dark");
    else el.setAttribute("data-theme", "light");
  } catch (_) {
    document.documentElement.setAttribute("data-theme", "light");
  }
})();
