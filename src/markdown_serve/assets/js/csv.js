import { escapeHtml } from "./utils.js";

/** RFC4180-ish parser: handles quoted fields, escaped quotes, CRLF/LF. */
function parseCsv(text, delimiter) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += c;
      }
      continue;
    }
    if (c === '"') {
      inQuotes = true;
    } else if (c === delimiter) {
      row.push(field);
      field = "";
    } else if (c === "\r") {
      // skip; \n (bare or in \r\n) ends the row
    } else if (c === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += c;
    }
  }
  if (field !== "" || row.length) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

function compareCells(a, b) {
  const na = Number(a);
  const nb = Number(b);
  if (a.trim() !== "" && b.trim() !== "" && !Number.isNaN(na) && !Number.isNaN(nb)) {
    return na - nb;
  }
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
}

export function renderCsvTable(
  text,
  { delimiter = ",", headerSkip = 0, footerSkip = 0, sortCol = null, sortDir = 1 } = {},
) {
  const delim = delimiter === "\\t" ? "\t" : (delimiter || ",")[0];
  let rows = parseCsv(text, delim);
  const start = Math.max(0, headerSkip);
  const end = footerSkip > 0 ? Math.max(start, rows.length - footerSkip) : rows.length;
  rows = rows.slice(start, end);
  if (!rows.length) {
    return '<p class="empty">No rows to display.</p>';
  }
  const [header, ...body] = rows;
  if (sortCol != null && sortCol < header.length) {
    body.sort((a, b) => sortDir * compareCells(a[sortCol] ?? "", b[sortCol] ?? ""));
  }
  const theadHtml =
    "<tr>" +
    header
      .map((cell, i) => {
        const dirClass = sortCol === i ? (sortDir === 1 ? " sort-asc" : " sort-desc") : "";
        return `<th data-col="${i}" class="sortable${dirClass}">${escapeHtml(cell)}</th>`;
      })
      .join("") +
    "</tr>";
  const bodyHtml = body
    .map((cells) => "<tr>" + cells.map((cell) => `<td>${escapeHtml(cell)}</td>`).join("") + "</tr>")
    .join("");
  return `<table class="csv-table"><thead>${theadHtml}</thead><tbody>${bodyHtml}</tbody></table>`;
}
