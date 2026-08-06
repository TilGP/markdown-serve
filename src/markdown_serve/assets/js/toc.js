import { content, toc, layout } from "./dom.js";
import { state } from "./state.js";
import { syncTocExpandButton } from "./layout.js";
import { fitWideTables } from "./diagrams.js";

export function clearToc() {
  if (state.tocObserver) {
    state.tocObserver.disconnect();
    state.tocObserver = null;
  }
  toc.innerHTML = "";
  layout.classList.add("no-toc");
  syncTocExpandButton();
}

function setTocActive(id) {
  toc.querySelectorAll("a").forEach((a) => {
    a.classList.toggle("active", a.getAttribute("href") === "#" + id);
  });
}

function buildNestedToc(headings) {
  const root = document.createElement("ol");
  root.className = "toc-list";
  const stack = [{ level: 0, list: root }];

  for (const heading of headings) {
    const level = Number(heading.tagName.slice(1));
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = "#" + heading.id;
    a.textContent = heading.textContent.replace(/\s*¶\s*$/, "").trim() || heading.id;
    a.addEventListener("click", (e) => {
      e.preventDefault();
      heading.scrollIntoView({ behavior: "smooth", block: "start" });
      history.replaceState(null, "", "#" + heading.id);
      setTocActive(heading.id);
    });
    li.appendChild(a);

    while (stack.length > 1 && stack[stack.length - 1].level >= level) {
      stack.pop();
    }

    const parent = stack[stack.length - 1];
    parent.list.appendChild(li);

    const nested = document.createElement("ol");
    nested.className = "toc-list";
    li.appendChild(nested);
    stack.push({ level, list: nested });
  }

  root.querySelectorAll("ol").forEach((ol) => {
    if (!ol.children.length) ol.remove();
  });
  return root;
}

export function updateToc() {
  clearToc();
  if (content.classList.contains("asset-mode")) return;

  const headings = [...content.querySelectorAll("h1[id], h2[id], h3[id], h4[id]")];
  if (!headings.length) return;

  layout.classList.remove("no-toc");
  layout.classList.toggle("toc-collapsed", state.tocCollapsedPref);
  syncTocExpandButton();
  toc.appendChild(buildNestedToc(headings));

  state.tocObserver = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (visible[0]?.target?.id) setTocActive(visible[0].target.id);
    },
    { rootMargin: "-10% 0px -70% 0px", threshold: [0, 1] },
  );
  for (const heading of headings) state.tocObserver.observe(heading);
  setTocActive(headings[0].id);
  requestAnimationFrame(fitWideTables);
}
