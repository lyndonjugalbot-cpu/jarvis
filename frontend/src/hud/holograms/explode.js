// The arithmetic behind breaking a model apart: where each part goes, how big the model can be
// drawn at a given explode amount, and how a two-hand spread maps to that amount. Plain arrays
// ([x, y, z], boxes as { min, max }) so it runs in tests without a scene.

const SPREAD_FULL = 0.6; // hands this much further apart (ratio 1.6) break the model fully apart
const SQUEEZE_FULL = 0.35; // hands this much closer (ratio 0.65) put it fully back together

const clamp01 = (v) => Math.max(0, Math.min(1, v));

// A two-hand gesture: `base` is the explode amount when it started, `ratio` the hands' distance
// now over their distance then.
export function spreadToExplode(base, ratio) {
  if (!Number.isFinite(ratio)) return clamp01(base);
  const delta = ratio >= 1 ? (ratio - 1) / SPREAD_FULL : -(1 - ratio) / SQUEEZE_FULL;
  return clamp01(base + delta);
}

// For a model without designed exploded positions (a .glb): each part moves straight out from
// the model's center, further the further out it already is, plus a little so parts at the
// center separate too. Parts right at the center go up and down alternately.
export function explodeVectors(centers, center, radius) {
  return centers.map((c, i) => {
    const d = [c[0] - center[0], c[1] - center[1], c[2] - center[2]];
    const length = Math.hypot(...d);
    if (length < radius * 0.02) {
      const up = (i % 2 ? -1 : 1) * radius * 0.35 * (1 + Math.floor(i / 2) * 0.3);
      return [0, up, 0];
    }
    const push = 0.9 + (radius * 0.12) / length;
    return d.map((v) => v * push);
  });
}

// The furthest any part's box reaches from `center` when every part has moved by offset * t.
export function reach(boxes, offsets, t, center) {
  let far = 0;
  boxes.forEach(({ min, max }, i) => {
    const o = offsets[i] ?? [0, 0, 0];
    for (const x of [min[0], max[0]]) {
      for (const y of [min[1], max[1]]) {
        for (const z of [min[2], max[2]]) {
          const d = Math.hypot(x + o[0] * t - center[0], y + o[1] * t - center[1], z + o[2] * t - center[2]);
          far = Math.max(far, d);
        }
      }
    }
  });
  return far;
}

// The scale that keeps the model inside a sphere of radius `room` while it turns, easing from the
// assembled size to the exploded one as it breaks apart.
export function fitScale(room, assembledReach, explodedReach, t) {
  const r = assembledReach + (explodedReach - assembledReach) * clamp01(t);
  return r > 0 ? room / r : 1;
}
