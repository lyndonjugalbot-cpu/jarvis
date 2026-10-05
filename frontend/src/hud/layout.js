// Ties the WebGL scene to the HTML dashboard: where an element's box sits in the 3D world (on the
// plane z = 0), and how many CSS pixels one world unit covers there.

export function createLayout(view) {
  // The element's box as a world-space rectangle: center x/y, width w, height h.
  function rectOf(el, z = 0) {
    const r = el.getBoundingClientRect();
    const W = window.innerWidth;
    const H = window.innerHeight;
    const a = view.pointAt(r.left / W, r.top / H, z);
    const b = view.pointAt(r.right / W, r.bottom / H, z);
    return {
      x: (a.x + b.x) / 2,
      y: (a.y + b.y) / 2,
      w: Math.abs(b.x - a.x),
      h: Math.abs(a.y - b.y),
      visible: r.width > 0 && r.height > 0,
    };
  }

  // CSS pixels per world unit at depth z, so panel text renders 1:1 at rest.
  function pxPerUnit(z = 0) {
    return window.innerHeight / view.viewSize(z).height;
  }

  return { rectOf, pxPerUnit };
}
