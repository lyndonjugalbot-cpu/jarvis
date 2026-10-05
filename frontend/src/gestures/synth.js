// Builds MediaPipe-shaped hands for tests and the replay demo.
//
// Hand space: wrist at the origin, y up, size 1 (wrist to middle knuckle), describing a right
// hand with its palm to the camera as seen in the mirrored view. Poses are bent fingers in that
// space; `place` rotates, mirrors (left hand, or the back of the hand) and maps it onto the image.

const MCP = { index: [-0.35, 0.95], middle: [0, 1], ring: [0.3, 0.95], pinky: [0.55, 0.85] };
const LENGTH = { index: 1, middle: 1.08, ring: 1, pinky: 0.8 };
const THUMB = {
  out: [[-0.2, 0.2], [-0.45, 0.35], [-0.7, 0.45], [-0.92, 0.55]],
  tucked: [[-0.2, 0.2], [-0.35, 0.35], [-0.3, 0.55], [-0.15, 0.7]],
  side: [[-0.2, 0.2], [-0.45, 0.35], [-0.75, 0.4], [-1.05, 0.45]],
  pinch: [[-0.2, 0.2], [-0.45, 0.4], [-0.6, 0.7], [-0.62, 1.0]],
};
const PINCH_INDEX = [[-0.35, 0.95], [-0.45, 1.3], [-0.55, 1.25], [-0.6, 1.05]];

function finger(name, state) {
  const [mx, my] = MCP[name];
  const n = Math.hypot(mx, my);
  const k = LENGTH[name];
  const at = (t) => [mx + (mx / n) * t * k, my + (my / n) * t * k];
  return state === "out" ? [[mx, my], at(0.45), at(0.73), at(0.95)] : [[mx, my], at(0.3), at(0.05), at(-0.35)];
}

const POSES = {
  open_palm: { thumb: "out", fingers: ["out", "out", "out", "out"] },
  fist: { thumb: "tucked", fingers: ["in", "in", "in", "in"] },
  point: { thumb: "tucked", fingers: ["out", "in", "in", "in"] },
  pinch: { thumb: "pinch", fingers: ["pinch", "out", "out", "out"] },
  thumbs_up: { thumb: "side", fingers: ["in", "in", "in", "in"], rotate: -90 },
  thumbs_down: { thumb: "side", fingers: ["in", "in", "in", "in"], rotate: 90 },
};

export function handSpace(pose) {
  const spec = POSES[pose];
  if (!spec) throw new Error(`unknown pose ${pose}`);
  const points = [[0, 0], ...THUMB[spec.thumb]];
  ["index", "middle", "ring", "pinky"].forEach((name, i) => {
    points.push(...(spec.fingers[i] === "pinch" ? PINCH_INDEX : finger(name, spec.fingers[i])));
  });
  return { points, rotate: spec.rotate ?? 0 };
}

// MediaPipe's label for a hand seen in an unmirrored camera frame is the opposite hand.
export function mediapipeLabel(hand) {
  return hand === "Right" ? "Left" : "Right";
}

export function place({ pose, x = 0.5, y = 0.6, size = 0.18, rotate = 0, hand = "Right", back = false, score = 0.95 }, aspect = 4 / 3) {
  const { points, rotate: poseRotate } = handSpace(pose);
  const angle = ((poseRotate + rotate) * Math.PI) / 180;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  const flip = (hand === "Left") !== back ? -1 : 1;
  const landmarks = points.map(([px, py]) => {
    const rx = px * cos - py * sin;
    const ry = px * sin + py * cos;
    return { x: x + (flip * rx * size) / aspect, y: y - ry * size, z: 0 };
  });
  return { handedness: mediapipeLabel(hand), score, landmarks };
}

// A scripted session: chain hold/move/gap calls, then read `.frames`.
export function session({ fps = 30, aspect = 4 / 3, start = 0 } = {}) {
  const frames = [];
  const step = 1000 / fps;
  let t = start;
  const lerp = (a, b, k) => a + (b - a) * k;
  const api = {
    frames,
    // move(ms, [fromSpec, toSpec], [fromSpec, toSpec], ...) - one pair per visible hand
    move(ms, ...pairs) {
      const n = Math.max(1, Math.round(ms / step));
      for (let i = 0; i < n; i++) {
        const k = n === 1 ? 1 : i / (n - 1);
        const hands = pairs.map(([from, to = from]) => {
          const spec = { ...from, ...(k >= 0.5 ? { pose: to.pose ?? from.pose } : {}) };
          for (const key of ["x", "y", "size", "rotate"]) {
            if (from[key] !== undefined || to[key] !== undefined) {
              spec[key] = lerp(from[key] ?? to[key], to[key] ?? from[key], k);
            }
          }
          return place(spec, aspect);
        });
        frames.push({ t: Math.round(t), aspect, hands });
        t += step;
      }
      return api;
    },
    hold(ms, ...specs) {
      return api.move(ms, ...specs.map((spec) => [spec, spec]));
    },
    gap(ms) {
      return api.move(ms);
    },
  };
  return api;
}
