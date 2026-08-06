const MARKDOWN_EXT = new Set(["md", "markdown", "mdown", "mkd"]);
const IMAGE_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "ico", "avif"]);
const PDF_EXT = new Set(["pdf"]);

export function extOf(path) {
  const i = path.lastIndexOf(".");
  return i >= 0 ? path.slice(i + 1).toLowerCase() : "";
}

export function fileKind(path) {
  const ext = extOf(path);
  if (MARKDOWN_EXT.has(ext)) return "markdown";
  if (PDF_EXT.has(ext)) return "pdf";
  if (IMAGE_EXT.has(ext)) return "image";
  return "other";
}

export function encodePath(path) {
  return path.split("/").map(encodeURIComponent).join("/");
}

export function basename(path) {
  const i = path.lastIndexOf("/");
  return i >= 0 ? path.slice(i + 1) : path;
}

export function dirname(path) {
  const i = path.lastIndexOf("/");
  return i >= 0 ? path.slice(0, i) : "";
}

export function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[c]);
}

export function fuzzyScore(query, candidate) {
  if (!query) return 1;
  if (query.startsWith("'")) {
    return exactScore(query.slice(1), candidate);
  }
  const q = query.toLowerCase();
  const name = basename(candidate).toLowerCase();
  const full = candidate.toLowerCase();
  let score = scoreSubsequence(q, name);
  if (score < 0) {
    score = scoreSubsequence(q, full);
    if (score >= 0) score *= 0.55;
  } else {
    score += 8;
  }
  return score;
}

function exactScore(query, candidate) {
  if (!query) return 1;
  const q = query.toLowerCase();
  const name = basename(candidate).toLowerCase();
  const full = candidate.toLowerCase();
  const nameIdx = name.indexOf(q);
  if (nameIdx >= 0) {
    let score = 1000 - nameIdx * 2;
    if (name === q) score += 200;
    else if (name.startsWith(q)) score += 80;
    return score;
  }
  const fullIdx = full.indexOf(q);
  if (fullIdx >= 0) return 400 - fullIdx;
  return -1;
}

function scoreSubsequence(query, text) {
  let qi = 0, score = 0, prev = -2, run = 0;
  for (let i = 0; i < text.length && qi < query.length; i++) {
    if (text[i] !== query[qi]) continue;
    run = i === prev + 1 ? run + 1 : 1;
    score += 1 + run * 3;
    if (i === 0 || "/-_ .".includes(text[i - 1])) score += 5;
    prev = i;
    qi++;
  }
  return qi === query.length ? score : -1;
}

export function lineFromLocation() {
  try {
    const sp = new URL(location.href).searchParams.get("line");
    if (sp && /^\d+$/.test(sp)) return Number(sp);
  } catch (_) {}
  const m = location.hash.match(/^#L(\d+)$/i);
  return m ? Number(m[1]) : null;
}
