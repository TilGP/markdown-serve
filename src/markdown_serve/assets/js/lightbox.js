import { content } from "./dom.js";

const MIN_SCALE = 0.05;
const MAX_SCALE = 40;
const FIT_PADDING = 32;
const RASTER_FIT_CAP = 2; // don't blow small bitmaps up past 2x on open
const DRAG_THRESHOLD = 4;
// Bitmap mode: rasterize huge SVGs so pan/zoom stays cheap. Safari caps canvas
// area at 16.7M px; stay under it and under a sane per-side limit.
const BITMAP_MAX_PIXELS = 16_000_000;
const BITMAP_MAX_SIDE = 8192;
const BITMAP_OVERSAMPLE = 1.5; // base layer: render above device DPR when the cap allows
const BITMAP_DETAIL_PAD = 0.25; // extra viewport fraction rendered on each side of the detail layer
const BITMAP_DETAIL_DELAY = 120; // ms of pan/zoom idle before re-rasterizing the visible region

const ENLARGE_ICON =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
  'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"></path></svg>';

let box = null; // lazily built overlay
// current { node, svgNode, bitmapNode, mode, width, height, raster, scale, x, y, fitScale, trigger }
let view = null;
const pointers = new Map();
let pressStart = null;
let preferBitmap = false; // remembered for the session once the user opts in

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
      <button type="button" class="lightbox-btn lightbox-bitmap-btn" data-action="bitmap" hidden
        aria-pressed="false" title="Render as bitmap for faster pan/zoom (B)" aria-label="Render as bitmap">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"></rect><circle cx="9" cy="10" r="1.6"></circle><path d="M21 16l-5-5-9 9"></path></svg>
      </button>
    </div>
    <div class="lightbox-viewport">
      <div class="lightbox-stage"></div>
    </div>
    <div class="lightbox-hint">scroll to zoom · drag to pan · double-click to toggle · <kbd>b</kbd> bitmap · <kbd>esc</kbd> to close</div>
  `;
  document.body.appendChild(root);

  const viewport = root.querySelector(".lightbox-viewport");
  const stage = root.querySelector(".lightbox-stage");
  const level = root.querySelector(".lightbox-level");
  const bitmapBtn = root.querySelector(".lightbox-bitmap-btn");

  root.querySelector(".lightbox-toolbar").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    const center = viewportCenter();
    switch (btn.dataset.action) {
      case "zoom-in": zoomAt(1.25, center.x, center.y); break;
      case "zoom-out": zoomAt(0.8, center.x, center.y); break;
      case "fit": fitToViewport(); break;
      case "actual": zoomTo(1, center.x, center.y); break;
      case "bitmap": toggleBitmapMode(); break;
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

  box = { root, viewport, stage, level, bitmapBtn };
}

// ---------------------------------------------------------------------------
// Bitmap mode (SVG -> canvas) for very large diagrams
// ---------------------------------------------------------------------------

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.decoding = "async";
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("SVG could not be rasterized"));
    img.src = url;
  });
}

function capPixelScale(scale, w, h) {
  return Math.min(
    scale,
    Math.sqrt(BITMAP_MAX_PIXELS / (w * h)),
    BITMAP_MAX_SIDE / w,
    BITMAP_MAX_SIDE / h,
  );
}

function makeCanvas(className, pixelW, pixelH, cssW, cssH) {
  const canvas = document.createElement("canvas");
  canvas.className = className;
  canvas.width = Math.max(1, Math.round(pixelW));
  canvas.height = Math.max(1, Math.round(pixelH));
  canvas.style.width = cssW + "px";
  canvas.style.height = cssH + "px";
  return canvas;
}

/**
 * Build the bitmap layers for an SVG:
 *  - base:   the whole diagram at a capped resolution (cheap overview while panning)
 *  - detail: a viewport-sized canvas re-rasterized for the visible region after
 *            each pan/zoom settles, so text stays sharp at any zoom level.
 * Both live in one wrapper sized like the SVG (in CSS px = diagram units), so the
 * stage transform applies unchanged.
 */
async function createBitmapLayers(svg, width, height) {
  const clone = svg.cloneNode(true);
  clone.removeAttribute("style");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  if (!clone.getAttribute("xmlns")) clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  if (!clone.getAttribute("xmlns:xlink")) {
    clone.setAttribute("xmlns:xlink", "http://www.w3.org/1999/xlink");
  }
  const xml = new XMLSerializer().serializeToString(clone);
  const url = URL.createObjectURL(new Blob([xml], { type: "image/svg+xml;charset=utf-8" }));
  let img;
  try {
    img = await loadImage(url);
  } catch (err) {
    URL.revokeObjectURL(url);
    throw err;
  }

  const dpr = window.devicePixelRatio || 1;
  const baseScale = capPixelScale(Math.max(1, dpr) * BITMAP_OVERSAMPLE, width, height);
  const base = makeCanvas("lightbox-bitmap-base", width * baseScale, height * baseScale, width, height);
  const baseCtx = base.getContext("2d");
  if (!baseCtx) {
    URL.revokeObjectURL(url);
    throw new Error("Canvas is unavailable");
  }
  baseCtx.drawImage(img, 0, 0, base.width, base.height);

  const detail = makeCanvas("lightbox-bitmap-detail", 1, 1, 1, 1);
  detail.style.display = "none";

  const node = document.createElement("div");
  node.className = "lightbox-bitmap";
  node.style.width = width + "px";
  node.style.height = height + "px";
  node.append(base, detail);

  return { node, img, url, base, baseScale, detail, detailKey: "", timer: null };
}

function releaseBitmapLayers(bm) {
  if (!bm) return;
  if (bm.timer != null) clearTimeout(bm.timer);
  bm.timer = null;
  URL.revokeObjectURL(bm.url);
}

// Re-rasterize the visible slice of the SVG at device resolution.
function renderBitmapDetail() {
  if (!view || view.mode !== "bitmap" || !view.bitmap) return;
  const bm = view.bitmap;
  const { scale, x, y, width, height } = view;
  const dpr = window.devicePixelRatio || 1;

  // Base already has enough pixels for this zoom level: nothing to do.
  if (scale * dpr <= bm.baseScale * 1.02) {
    bm.detail.style.display = "none";
    bm.detailKey = "";
    return;
  }

  const vw = box.viewport.clientWidth;
  const vh = box.viewport.clientHeight;
  // Visible diagram rect, padded so small pans don't immediately leave it.
  const padX = (vw / scale) * BITMAP_DETAIL_PAD;
  const padY = (vh / scale) * BITMAP_DETAIL_PAD;
  const sx = Math.max(0, -x / scale - padX);
  const sy = Math.max(0, -y / scale - padY);
  const ex = Math.min(width, (vw - x) / scale + padX);
  const ey = Math.min(height, (vh - y) / scale + padY);
  const sw = ex - sx;
  const sh = ey - sy;
  if (sw <= 0 || sh <= 0) {
    bm.detail.style.display = "none";
    bm.detailKey = "";
    return;
  }

  const pixelScale = capPixelScale(scale * dpr, sw, sh);
  const cw = Math.max(1, Math.round(sw * pixelScale));
  const ch = Math.max(1, Math.round(sh * pixelScale));
  const key = [sx, sy, sw, sh, cw, ch].map((v) => Math.round(v)).join(",");
  if (key === bm.detailKey && bm.detail.style.display !== "none") return;

  const ctx = bm.detail.getContext("2d");
  if (!ctx) return;
  bm.detail.width = cw;
  bm.detail.height = ch;
  bm.detail.style.left = sx + "px";
  bm.detail.style.top = sy + "px";
  bm.detail.style.width = sw + "px";
  bm.detail.style.height = sh + "px";
  try {
    ctx.clearRect(0, 0, cw, ch);
    ctx.drawImage(bm.img, sx, sy, sw, sh, 0, 0, cw, ch);
    bm.detail.style.display = "";
    bm.detailKey = key;
  } catch (err) {
    bm.detail.style.display = "none";
    bm.detailKey = "";
    console.warn("lightbox: detail rasterization failed", err);
  }
}

function scheduleBitmapDetail(delay = BITMAP_DETAIL_DELAY) {
  if (!view || view.mode !== "bitmap" || !view.bitmap) return;
  const bm = view.bitmap;
  if (bm.timer != null) clearTimeout(bm.timer);
  bm.timer = setTimeout(() => {
    bm.timer = null;
    requestAnimationFrame(renderBitmapDetail);
  }, delay);
}

function flashLevel(text, ms = 1600) {
  box.level.textContent = text;
  setTimeout(() => { if (view) applyTransform(); }, ms);
}

function syncBitmapButton() {
  const btn = box.bitmapBtn;
  if (!view || !view.svgNode) {
    btn.hidden = true;
    return;
  }
  btn.hidden = false;
  const on = view.mode === "bitmap";
  btn.setAttribute("aria-pressed", on ? "true" : "false");
  btn.title = on
    ? "Back to vector rendering (B)"
    : "Render as bitmap for faster pan/zoom (B)";
  btn.setAttribute("aria-label", on ? "Render as vector" : "Render as bitmap");
}

async function setRenderMode(mode) {
  if (!view || !view.svgNode || view.mode === mode || view.busy) return;
  const target = view;
  if (mode === "bitmap" && !target.bitmap) {
    target.busy = true;
    box.bitmapBtn.setAttribute("aria-busy", "true");
    box.level.textContent = "rendering…";
    try {
      const layers = await createBitmapLayers(target.svgNode, target.width, target.height);
      if (view !== target) { // closed or replaced while rendering
        releaseBitmapLayers(layers);
        return;
      }
      target.bitmap = layers;
    } catch (err) {
      if (view !== target) return;
      target.busy = false;
      box.bitmapBtn.removeAttribute("aria-busy");
      flashLevel("bitmap failed");
      console.warn("lightbox: bitmap rendering failed", err);
      return;
    }
    target.busy = false;
    box.bitmapBtn.removeAttribute("aria-busy");
  }
  if (mode !== "bitmap" && target.bitmap?.timer != null) {
    clearTimeout(target.bitmap.timer);
    target.bitmap.timer = null;
  }
  target.mode = mode;
  target.node = mode === "bitmap" ? target.bitmap.node : target.svgNode;
  // Same CSS size in both modes, so the current translate/scale stays valid.
  box.stage.replaceChildren(target.node);
  applyTransform();
  syncBitmapButton();
  if (mode === "bitmap") renderBitmapDetail();
}

function toggleBitmapMode() {
  if (!view || !view.svgNode) return;
  const next = view.mode === "bitmap" ? "svg" : "bitmap";
  preferBitmap = next === "bitmap";
  setRenderMode(next);
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
  view = {
    node,
    svgNode: raster ? null : node,
    bitmap: null,
    mode: "svg",
    busy: false,
    width, height, raster, scale: 1, x: 0, y: 0, fitScale: 1, trigger,
  };

  box.root.hidden = false;
  document.documentElement.classList.add("lightbox-open");
  fitToViewport();
  syncBitmapButton();
  box.root.focus({ preventScroll: true });
  if (!raster && preferBitmap) setRenderMode("bitmap");
}

export function closeLightbox() {
  if (!box || box.root.hidden) return;
  box.root.hidden = true;
  document.documentElement.classList.remove("lightbox-open");
  box.stage.replaceChildren();
  pointers.clear();
  pressStart = null;
  box.bitmapBtn.removeAttribute("aria-busy");
  releaseBitmapLayers(view?.bitmap);
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
  if (view.mode === "bitmap") scheduleBitmapDetail();
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
    case "b":
    case "B":
      e.preventDefault();
      toggleBitmapMode();
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
