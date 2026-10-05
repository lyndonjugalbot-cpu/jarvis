// Angled HUD frames (the chamfered boxes in HUD.png) for every `.frame` element: an SVG behind the
// content with a dark fill, a thin glowing outline, and brighter accents on two corners. The SVG
// is redrawn when the element changes size. `data-cut` sets the corner cut in pixels.

const SVG = "http://www.w3.org/2000/svg";
const DEFAULT_CUT = 12;
const ACCENT = 34; // length of the bright corner strokes

function path(w, h, c) {
  // Cut the top-left and bottom-right corners; the other two stay square.
  return `M${c} .5H${w - 0.5}V${h - c}L${w - c} ${h - 0.5}H.5V${c}Z`;
}

function accents(w, h, c) {
  return (
    `M.5 ${c + ACCENT}V${c}L${c} .5H${c + ACCENT}` +
    `M${w - 0.5} ${h - c - ACCENT}V${h - c}L${w - c} ${h - 0.5}H${w - c - ACCENT}`
  );
}

function node(tag, className) {
  const el = document.createElementNS(SVG, tag);
  el.setAttribute("class", className);
  return el;
}

function attach(el) {
  const svg = node("svg", "frame-svg");
  svg.setAttribute("aria-hidden", "true");
  const fill = node("path", "frame-fill");
  const stroke = node("path", "frame-stroke");
  const accent = node("path", "frame-accent");
  svg.append(fill, stroke, accent);
  el.prepend(svg);
  const cut = Number(el.dataset.cut ?? DEFAULT_CUT);

  const draw = () => {
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    if (!w || !h) return;
    const c = Math.min(cut, w / 4, h / 4);
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    fill.setAttribute("d", path(w, h, c));
    stroke.setAttribute("d", path(w, h, c));
    accent.setAttribute("d", accents(w, h, c));
  };
  new ResizeObserver(draw).observe(el);
  draw();
}

export function drawFrames(root = document) {
  for (const el of root.querySelectorAll(".frame")) {
    if (!el.querySelector(":scope > .frame-svg")) attach(el);
  }
}
