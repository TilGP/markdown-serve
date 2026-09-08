import { content } from "./dom.js";

const MIN_SCALE = 0.05;
const MAX_SCALE = 40;
const FIT_PADDING = 32;
const RASTER_FIT_CAP = 2; // don't blow small bitmaps up past 2x on open
const DRAG_THRESHOLD = 4;

const ENLARGE_ICON =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
  'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"></path></svg>';

let box = null; // lazily built overlay
let view = null; // current { node, width, height, raster, scale, x, y, fitScale, trigger }
const pointers = new Map();
let pressStart = null;

// ---------------------------------------------------------------------------
// Buttons on artifacts
// ---------------------------------------------------------------------------

function wrapWithButton(el, tag, className, resolveTarget) {
  const wrapper = document.createElement(tag);
  wrapper.className = "zoomable " + className;
  el.parentNode.insertBefore(wrapper, el);
  wrapper.appendChild(el);

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "zoom-btn";
  btn.title = "Enlarge";
  btn.setAttribute("aria-label", "Enlarge");
  btn.innerHTML = ENLARGE_ICON;
  btn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    const target = resolveTarget();
    if (target) openLightbox(target, btn);
  });
  wrapper.appendChild(btn);
}

export function enhanceZoomables() {
  for (const img of [...content.querySelectorAll("img")]) {
    if (img.closest(".zoomable") || img.closest(".diagram")) continue;
    if (img.complete && img.naturalWidth === 0) continue; // broken image
    // Wrap the link instead when the image is the only thing inside it.
    const parent = img.parentElement;
    const host = parent && parent.tagName === "A" && parent.childNodes.length === 1 ? parent : img;
    // Images inside paragraphs stay inline; the asset preview sits directly in #content.
    const tag = host.parentElement === content ? "div" : "span";
    wrapWithButton(host, tag, "zoomable-inline", () => img);
  }
  for (const diagram of [...content.querySelectorAll(".diagram-mermaid, .diagram-plantuml")]) {
    if (diagram.closest(".zoomable")) continue;
    if (!diagram.querySelector(":scope > svg")) continue;
    wrapWithButton(diagram, "div", "zoomable-block", () => diagram.querySelector(":scope > svg"));
  }
}

// ---------------------------------------------------------------------------
// Overlay
// ---------------------------------------------------------------------------

function buildLightbox() {
  const root = document.createElement("div");
  root.className = "lightbox";
  root.hidden = true;
  root.tabIndex = -1;
  root.setAttribute("role", "dialog");
  root.setAttribute("aria-modal", "true");
  root.setAttribute("aria-label", "Enlarged view");
  root.innerHTML = `
    <div class="lightbox-toolbar" role="toolbar" aria-label="Zoom controls">
      <button type="button" class="lightbox-btn" data-action="close" title="Close (Esc)" aria-label="Close">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"></path></svg>
      </button>
      <button type="button" class="lightbox-btn" data-action="fit" title="Fit to screen (0)" aria-label="Fit to screen">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 3H3v6M15 3h6v6M9 21H3v-6M15 21h6v-6"></path></svg>
      </button>
      <button type="button" class="lightbox-btn" data-action="actual" title="Actual size (1)" aria-label="Actual size">
        <span class="lightbox-btn-text">1:1</span>
      </button>
      <button type="button" class="lightbox-btn" data-action="zoom-in" title="Zoom in (+)" aria-label="Zoom in">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"></path></svg>
      </button>
      <button type="button" class="lightbox-btn" data-action="zoom-out" title="Zoom out (−)" aria-label="Zoom out">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M5 12h14"></path></svg>
      </button>
      <span class="lightbox-level" aria-live="polite">100%</span>
    </div>
    <div class="lightbox-viewport">
      <div class="lightbox-stage"></div>
    </div>
    <div class="lightbox-hint">scroll to zoom · drag to pan · double-click to toggle · <kbd>esc</kbd> to close</div>
  `;
  document.body.appendChild(root);

  const viewport = root.querySelector(".lightbox-viewport");
  const stage = root.querySelector(".lightbox-stage");
  const level = root.querySelector(".lightbox-level");

  root.querySelector(".lightbox-toolbar").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const center = viewportCenter();
    switch (btn.dataset.action) {
      case "zoom-in": zoomAt(1.25, center.x, center.y); break;
      case "zoom-out": zoomAt(0.8, center.x, center.y); break;
      case "fit": fitToViewport(); break;
      case "actual": zoomTo(1, center.x, center.y); break;
      case "close": closeLightbox(); break;
      default: break;
    }
  });

  viewport.addEventListener("wheel", onWheel, { passive: false });
  viewport.addEventListener("pointerdown", onPointerDown);
  viewport.addEventListener("pointermove", onPointerMove);
  viewport.addEventListener("pointerup", onPointerUp);
  viewport.addEventListener("pointercancel", onPointerUp);
  viewport.addEventListener("dblclick", onDoubleClick);
  viewport.addEventListener("dragstart", (e) => e.preventDefault());
  root.addEventListener("keydown", onKeyDown);
  window.addEventListener("resize", () => {
    if (view && !root.hidden) fitToViewport();
  });

  box = { root, viewport, stage, level };
}

function svgNaturalSize(svg) {
  const attrW = Number.parseFloat(svg.getAttribute("width") || "");
  const attrH = Number.parseFloat(svg.getAttribute("height") || "");
  const pctW = /%\s*$/.test(svg.getAttribute("width") || "");
  const pctH = /%\s*$/.test(svg.getAttribute("height") || "");
  if (Number.isFinite(attrW) && attrW > 0 && !pctW && Number.isFinite(attrH) && attrH > 0 && !pctH) {
    return { width: attrW, height: attrH };
  }
  const vb = svg.viewBox?.baseVal;
  if (vb && vb.width > 0 && vb.height > 0) {
    return { width: vb.width, height: vb.height };
  }
  const rect = svg.getBoundingClientRect();
  return { width: Math.max(1, rect.width), height: Math.max(1, rect.height) };
}

function cloneArtifact(el) {
  if (el.tagName === "IMG") {
    const img = new Image();
    img.alt = el.alt || "";
    img.draggable = false;
    img.className = "lightbox-image";
    img.src = el.currentSrc || el.src;
    const fromEl = el.naturalWidth > 0
      ? { width: el.naturalWidth, height: el.naturalHeight }
      : null;
    const ready = fromEl
      ? Promise.resolve(fromEl)
      : new Promise((resolve) => {
        const done = () => resolve({
          width: img.naturalWidth || el.getBoundingClientRect().width || 1,
          height: img.naturalHeight || el.getBoundingClientRect().height || 1,
        });
        img.addEventListener("load", done, { once: true });
        img.addEventListener("error", done, { once: true });
        if (img.complete) done();
      });
    return { node: img, ready, raster: true };
  }

  const size = svgNaturalSize(el);
  const clone = el.cloneNode(true);
  clone.classList.add("lightbox-svg");
  clone.removeAttribute("style");
  clone.setAttribute("width", String(size.width));
  clone.setAttribute("height", String(size.height));
  clone.style.width = size.width + "px";
  clone.style.height = size.height + "px";
  clone.style.maxWidth = "none";
  clone.style.display = "block";
  return { node: clone, ready: Promise.resolve(size), raster: false };
}

export async function openLightbox(el, trigger = null) {
  if (!box) buildLightbox();
  const { node, ready, raster } = cloneArtifact(el);
  const { width, height } = await ready;

  pointers.clear();
  pressStart = null;
  node.style.width = width + "px";
  node.style.height = height + "px";
  box.stage.replaceChildren(node);
  view = { node, width, height, raster, scale: 1, x: 0, y: 0, fitScale: 1, trigger };

  box.root.hidden = false;
  document.documentElement.classList.add("lightbox-open");
  fitToViewport();
  box.root.focus({ preventScroll: true });
}

export function closeLightbox() {
  if (!box || box.root.hidden) return;
  box.root.hidden = true;
  document.documentElement.classList.remove("lightbox-open");
  box.stage.replaceChildren();
  pointers.clear();
  pressStart = null;
  const trigger = view?.trigger;
  view = null;
  if (trigger && trigger.isConnected) {
    trigger.focus({ preventScroll: true });
  }
}

// ---------------------------------------------------------------------------
// Transform helpers
// ---------------------------------------------------------------------------

function clampScale(s) {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, s));
}

function viewportCenter() {
  return { x: box.viewport.clientWidth / 2, y: box.viewport.clientHeight / 2 };
}

function applyTransform() {
  if (!view) return;
  box.stage.style.transform =
    `translate(${view.x}px, ${view.y}px) scale(${view.scale})`;
  box.level.textContent = Math.round(view.scale * 100) + "%";
}

function fitToViewport() {
  if (!view) return;
  const vw = box.viewport.clientWidth;
  const vh = box.viewport.clientHeight;
  let s = Math.min((vw - FIT_PADDING) / view.width, (vh - FIT_PADDING) / view.height);
  if (view.raster) s = Math.min(s, RASTER_FIT_CAP);
  s = clampScale(s);
  view.fitScale = s;
  view.scale = s;
  view.x = (vw - view.width * s) / 2;
  view.y = (vh - view.height * s) / 2;
  applyTransform();
}

function zoomTo(nextScale, px, py) {
  if (!view) return;
  const s = clampScale(nextScale);
  const ratio = s / view.scale;
  view.x = px - (px - view.x) * ratio;
  view.y = py - (py - view.y) * ratio;
  view.scale = s;
  applyTransform();
}

function zoomAt(factor, px, py) {
  if (!view) return;
  zoomTo(view.scale * factor, px, py);
}

function panBy(dx, dy) {
  if (!view) return;
  view.x += dx;
  view.y += dy;
  applyTransform();
}

function localPoint(e) {
  const rect = box.viewport.getBoundingClientRect();
  return { x: e.clientX - rect.left, y: e.clientY - rect.top };
}

// ---------------------------------------------------------------------------
// Input handlers
// ---------------------------------------------------------------------------

function onWheel(e) {
  if (!view) return;
  e.preventDefault();
  let delta = e.deltaY;
  if (e.deltaMode === 1) delta *= 16; // lines -> px
  else if (e.deltaMode === 2) delta *= box.viewport.clientHeight; // pages -> px
  // ctrlKey is set for trackpad pinch gestures; they need a stronger response.
  const sensitivity = e.ctrlKey ? 0.01 : 0.0022;
  const factor = Math.exp(-delta * sensitivity);
  const p = localPoint(e);
  zoomAt(factor, p.x, p.y);
}

function onPointerDown(e) {
  if (!view) return;
  if (e.pointerType === "mouse" && e.button !== 0) return;
  e.preventDefault();
  box.viewport.setPointerCapture(e.pointerId);
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (pointers.size === 1) {
    pressStart = {
      x: e.clientX,
      y: e.clientY,
      onBackdrop: !box.stage.contains(e.target),
      moved: false,
    };
  } else {
    pressStart = null;
  }
  box.viewport.classList.add("is-dragging");
}

function onPointerMove(e) {
  if (!view || !pointers.has(e.pointerId)) return;
  const prev = pointers.get(e.pointerId);
  const next = { x: e.clientX, y: e.clientY };

  if (pointers.size === 1) {
    if (pressStart && !pressStart.moved) {
      const dist = Math.hypot(next.x - pressStart.x, next.y - pressStart.y);
      if (dist > DRAG_THRESHOLD) pressStart.moved = true;
    }
    pointers.set(e.pointerId, next);
    panBy(next.x - prev.x, next.y - prev.y);
    return;
  }

  // Two (or more) pointers: pinch to zoom around the midpoint and pan with it.
  const ids = [...pointers.keys()].slice(0, 2);
  const a0 = pointers.get(ids[0]);
  const b0 = pointers.get(ids[1]);
  pointers.set(e.pointerId, next);
  const a1 = pointers.get(ids[0]);
  const b1 = pointers.get(ids[1]);

  const prevMid = { x: (a0.x + b0.x) / 2, y: (a0.y + b0.y) / 2 };
  const nextMid = { x: (a1.x + b1.x) / 2, y: (a1.y + b1.y) / 2 };
  const prevDist = Math.hypot(a0.x - b0.x, a0.y - b0.y) || 1;
  const nextDist = Math.hypot(a1.x - b1.x, a1.y - b1.y) || 1;

  panBy(nextMid.x - prevMid.x, nextMid.y - prevMid.y);
  const rect = box.viewport.getBoundingClientRect();
  zoomAt(nextDist / prevDist, nextMid.x - rect.left, nextMid.y - rect.top);
}

function onPointerUp(e) {
  if (!pointers.has(e.pointerId)) return;
  pointers.delete(e.pointerId);
  try { box.viewport.releasePointerCapture(e.pointerId); } catch (_) {}
  if (pointers.size === 0) {
    box.viewport.classList.remove("is-dragging");
    const press = pressStart;
    pressStart = null;
    if (press && press.onBackdrop && !press.moved && e.type === "pointerup") {
      closeLightbox();
    }
  }
}

function onDoubleClick(e) {
  if (!view) return;
  e.preventDefault();
  const p = localPoint(e);
  const nearFit = Math.abs(view.scale - view.fitScale) < 0.01;
  if (nearFit) {
    zoomTo(Math.max(1, view.fitScale * 2.5), p.x, p.y);
  } else {
    fitToViewport();
  }
}

function onKeyDown(e) {
  if (!view) return;
  e.stopPropagation(); // modal: keep global shortcuts (e.g. "/") from firing underneath
  const center = viewportCenter();
  const step = 48;
  switch (e.key) {
    case "Escape":
      e.preventDefault();
      closeLightbox();
      break;
    case "+":
    case "=":
      e.preventDefault();
      zoomAt(1.25, center.x, center.y);
      break;
    case "-":
    case "_":
      e.preventDefault();
      zoomAt(0.8, center.x, center.y);
      break;
    case "0":
      e.preventDefault();
      fitToViewport();
      break;
    case "1":
      e.preventDefault();
      zoomTo(1, center.x, center.y);
      break;
    case "ArrowLeft":
      e.preventDefault();
      panBy(step, 0);
      break;
    case "ArrowRight":
      e.preventDefault();
      panBy(-step, 0);
      break;
    case "ArrowUp":
      e.preventDefault();
      panBy(0, step);
      break;
    case "ArrowDown":
      e.preventDefault();
      panBy(0, -step);
      break;
    default:
      break;
  }
}
