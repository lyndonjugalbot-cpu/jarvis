// The shape of one hand in one frame.
//
// Landmarks are MediaPipe's 21 points in normalized image coordinates, already mirrored so x
// grows toward the user's right (like looking in a mirror). `aspect` (width / height) makes
// x and y distances comparable. All distances are divided by the hand size h (wrist to middle
// knuckle), so the rules work at any distance from the camera.

const FINGERS = { index: [6, 8], middle: [10, 12], ring: [14, 16], pinky: [18, 20] };
const FOUR = Object.keys(FINGERS);

export function trueHandedness(label, settings) {
  // MediaPipe labels hands as if the image were mirrored; the tracker passes it the raw camera
  // frame, so its "Left" is really the user's right hand.
  if (!settings.swapHandedness) return label;
  return label === "Left" ? "Right" : "Left";
}

export function measure(landmarks, aspect, hand, s) {
  const P = landmarks.map((p) => ({ x: p.x * aspect, y: p.y }));
  const d = (a, b) => Math.hypot(P[a].x - P[b].x, P[a].y - P[b].y);
  const size = Math.max(d(0, 9), 1e-6);

  const fingers = {};
  for (const [name, [pip, tip]] of Object.entries(FINGERS)) {
    const ratio = d(0, tip) / Math.max(d(0, pip), 1e-6);
    fingers[name] =
      ratio > s.fingerExtendedRatio ? "extended" : ratio < s.fingerCurledRatio ? "curled" : "between";
  }

  const thumbReach = d(4, 5) / size;
  const thumb =
    thumbReach >= s.thumbExtendedMin ? "extended" : thumbReach < s.thumbTuckedMax ? "tucked" : "between";
  const tx = P[4].x - P[2].x;
  const ty = P[4].y - P[2].y;
  const thumbAngle = (Math.acos(Math.max(-1, Math.min(1, -ty / (Math.hypot(tx, ty) || 1e-6)))) * 180) / Math.PI;

  // Palm toward the camera: in the mirrored view a right palm has the index knuckle on the left
  // of the pinky knuckle (when upright), which makes this cross product positive at any rotation.
  const ax = P[5].x - P[0].x;
  const ay = P[5].y - P[0].y;
  const bx = P[17].x - P[0].x;
  const by = P[17].y - P[0].y;
  const cross = ax * by - ay * bx;
  const palmFacing = hand === "Right" ? cross > 0 : cross < 0;

  const at = (i) => ({ x: landmarks[i].x, y: landmarks[i].y });
  return {
    size,
    fingers,
    thumb,
    thumbAngle,
    palmFacing,
    pinch: d(4, 8) / size,
    indexReach: d(0, 8) / size,
    wrist: at(0),
    indexTip: at(8),
    pinchPoint: { x: (landmarks[4].x + landmarks[8].x) / 2, y: (landmarks[4].y + landmarks[8].y) / 2 },
  };
}

export function classify(f, s, wasPinching = false) {
  const curled = FOUR.every((n) => f.fingers[n] === "curled");
  if (f.pinch < (wasPinching ? s.pinchOff : s.pinchOn) && f.indexReach > s.pinchMinReach) return "pinch";
  if (curled && f.thumb === "tucked") return "fist";
  if (curled && f.thumb === "extended") {
    if (f.thumbAngle <= s.thumbAngleMaxDeg) return "thumbs_up";
    if (f.thumbAngle >= 180 - s.thumbAngleMaxDeg) return "thumbs_down";
  }
  const open = FOUR.every((n) => f.fingers[n] === "extended") && f.thumb === "extended";
  if (open && (f.palmFacing || !s.requirePalmFacing)) return "open_palm";
  if (f.fingers.index === "extended" && FOUR.slice(1).every((n) => f.fingers[n] === "curled")) {
    return "point";
  }
  return "other";
}

// How full the cursor's pinch ring is: 0 = fingers apart, 1 = pinching.
export function pinchStrength(f, s) {
  const span = 0.9 - s.pinchOn;
  return Math.max(0, Math.min(1, 1 - (f.pinch - s.pinchOn) / span));
}
