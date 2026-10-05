// Debug overlay (press D): camera view with the tracked hands, each hand's pose and speed, the
// frame rate and the latest gesture events. Useful for tuning thresholds in the settings drawer.

const BONES = [
  [0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11],
  [11, 12], [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [17, 18], [18, 19], [19, 20], [0, 17],
];
const QUIET = new Set(["cursor", "charge", "drag_move", "two_hand_update"]);

export function createDebug(el, video) {
  const canvas = el.querySelector("canvas");
  const info = el.querySelector(".debug-info");
  const log = el.querySelector(".debug-log");
  const ctx = canvas.getContext("2d");
  const recent = [];

  return {
    get visible() {
      return !el.hidden;
    },
    toggle(force) {
      el.hidden = force === undefined ? !el.hidden : !force;
    },
    show(frame, hands, events, { fps, armed, source }) {
      for (const e of events) {
        if (QUIET.has(e.type)) continue;
        recent.unshift(e.type === "swipe" ? `swipe ${e.direction}` : e.type);
        recent.length = Math.min(recent.length, 6);
      }
      if (el.hidden) return;

      const W = canvas.width;
      const H = canvas.height;
      ctx.fillStyle = "#05080f";
      ctx.fillRect(0, 0, W, H);
      if (source === "camera" && video.readyState >= 2) {
        ctx.save();
        ctx.globalAlpha = 0.45;
        ctx.translate(W, 0);
        ctx.scale(-1, 1); // mirror, to match the mirrored landmarks
        ctx.drawImage(video, 0, 0, W, H);
        ctx.restore();
      }
      ctx.strokeStyle = "#22d3ee";
      ctx.fillStyle = "#22d3ee";
      ctx.lineWidth = 2;
      for (const hand of frame?.hands ?? []) {
        const p = hand.landmarks.map((l) => [l.x * W, l.y * H]);
        ctx.beginPath();
        for (const [a, b] of BONES) {
          ctx.moveTo(...p[a]);
          ctx.lineTo(...p[b]);
        }
        ctx.stroke();
        for (const [x, y] of p) ctx.fillRect(x - 2, y - 2, 4, 4);
      }

      const rate = source === "camera" ? ` | ${fps.toFixed(0)} fps` : "";
      const lines = [`${source}${rate} | ${armed ? "armed" : "disarmed"}`];
      for (const h of hands) lines.push(`${h.key}: ${h.pose} | ${h.speed.toFixed(1)} h/s`);
      info.textContent = lines.join("\n");
      log.textContent = recent.join("\n");
    },
  };
}
