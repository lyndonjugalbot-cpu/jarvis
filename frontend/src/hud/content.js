// Panel bodies for each panel type (spec 5.3): text, list, calendar, chart, image, files.
// Everything is built with DOM APIs and textContent, never innerHTML, since data can come from
// web pages and emails.

const SVG = "http://www.w3.org/2000/svg";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function svg(tag, attrs) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

function list(data) {
  const ul = el("ul");
  for (const item of Array.isArray(data) ? data : [data]) ul.append(el("li", "", String(item)));
  return ul;
}

function calendar(events) {
  const ol = el("ol", "agenda");
  for (const event of Array.isArray(events) ? events : []) {
    const li = el("li");
    const when = [event.start, event.end].filter(Boolean).join(" - ") || (event.all_day ? "all day" : "");
    li.append(el("time", "", when), el("span", "what", String(event.title ?? "")));
    if (event.location) li.append(el("small", "", String(event.location)));
    ol.append(li);
  }
  if (!ol.children.length) ol.append(el("li", "empty", "Nothing scheduled."));
  return ol;
}

function chart({ labels = [], values = [], kind = "bar", unit = "" }) {
  const W = 340;
  const H = 150;
  const pad = { left: 34, right: 8, top: 10, bottom: 22 };
  const max = Math.max(...values, 0) || 1;
  const step = (W - pad.left - pad.right) / Math.max(values.length, 1);
  const y = (v) => pad.top + (H - pad.top - pad.bottom) * (1 - v / max);
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img" });
  root.append(svg("line", { x1: pad.left, y1: y(0), x2: W - pad.right, y2: y(0), class: "axis" }));
  const top = svg("text", { x: pad.left - 4, y: pad.top + 4, "text-anchor": "end", class: "tick" });
  top.textContent = `${Number(max.toFixed(2))}${unit}`;
  root.append(top);
  const points = [];
  values.forEach((value, i) => {
    const cx = pad.left + step * (i + 0.5);
    if (kind === "line") points.push(`${cx},${y(value)}`);
    else root.append(svg("rect", { x: cx - step * 0.3, y: y(value), width: step * 0.6, height: y(0) - y(value), class: "bar" }));
    const label = svg("text", { x: cx, y: H - 6, "text-anchor": "middle", class: "tick" });
    label.textContent = String(labels[i] ?? "");
    root.append(label);
  });
  if (kind === "line") root.append(svg("polyline", { points: points.join(" "), class: "line" }));
  return root;
}

function image({ url = "", caption = "" }) {
  const figure = el("figure");
  if (/^https?:\/\//.test(url)) {
    const img = el("img");
    img.src = url;
    img.alt = caption;
    img.referrerPolicy = "no-referrer";
    figure.append(img);
  }
  if (caption) figure.append(el("figcaption", "", caption));
  return figure;
}

const FOLDER_ICON = "M3 6.5A1.5 1.5 0 0 1 4.5 5h5l2 2.5h8A1.5 1.5 0 0 1 21 9v9.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5Z";
const DOC_ICON = "M6 3h8l4 4v14H6ZM14 3v4h4M9 12h6M9 15.5h6";

function when(modified) {
  const date = new Date(String(modified).replace(" ", "T"));
  if (Number.isNaN(date.getTime())) return String(modified ?? "");
  const days = Math.floor((new Date().setHours(0, 0, 0, 0) - new Date(date).setHours(0, 0, 0, 0)) / 864e5);
  if (days === 0) return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (days === 1) return "yesterday";
  return date.toLocaleDateString([], { day: "numeric", month: "short", year: days > 300 ? "numeric" : undefined });
}

function sizeText(kb) {
  if (typeof kb !== "number") return "";
  return kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${Math.max(kb, 0.1)} KB`;
}

function fileMeta(row) {
  if (row.folder) return "Folder";
  const ext = /\.([a-z0-9]{1,6})$/i.exec(String(row.name))?.[1]?.toUpperCase();
  return [ext, row.modified ? when(row.modified) : "", sizeText(row.size_kb)].filter(Boolean).join("  \u2022  ");
}

function files({ folder = "", files: rows = [] }) {
  const box = el("div", "files");
  const head = el("div", "files-head");
  head.append(el("span", "files-folder", folder || "Results"), el("span", "files-count", `${rows.length} results`));
  const ul = el("ul", "file-rows");
  for (const row of rows) {
    const li = el("li", "file-row");
    const path = String(row.path ?? row.name).replace(/^~\//, "");
    li.title = String(row.path ?? row.name);
    const icon = svg("svg", { viewBox: "0 0 24 24", class: row.folder ? "folder-icon" : "doc-icon", "aria-hidden": "true" });
    icon.append(svg("path", { d: row.folder ? FOLDER_ICON : DOC_ICON }));
    const text = el("span", "file-text");
    text.append(el("span", "file-name", path), el("span", "file-meta", fileMeta(row)));
    li.append(icon, text, el("span", "chev", "\u203a"));
    ul.append(li);
  }
  box.append(head, ul);
  return box;
}

export function renderBody(type, data) {
  if (type === "files") return files(Array.isArray(data) ? { files: data } : (data ?? {}));
  if (type === "list") return list(data);
  if (type === "calendar") return calendar(data);
  if (type === "chart") return chart(data ?? {});
  if (type === "image") return image(data ?? {});
  return el("p", "", typeof data === "string" ? data : JSON.stringify(data));
}
