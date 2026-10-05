// Every gesture threshold in one place. The settings drawer (press S) is generated from SETTINGS,
// so each value can be tuned live. Distances are in hand sizes (h: wrist to middle knuckle),
// speeds in hand sizes per second, times in milliseconds.

export const SETTINGS = [
  // Tracking
  { key: "minConfidence", value: 0.6, min: 0, max: 1, step: 0.05, label: "Ignore hands below this confidence" },
  { key: "stableFrames", value: 4, min: 1, max: 10, step: 1, label: "Frames a pose must hold before it counts" },
  { key: "lostGraceMs", value: 120, min: 0, max: 500, step: 10, label: "Keep a hand this long after it drops out" },
  { key: "smoothMinCutoff", value: 1.5, min: 0.1, max: 10, step: 0.1, label: "Smoothing when still (One Euro min cutoff)" },
  { key: "smoothBeta", value: 8, min: 0, max: 50, step: 0.5, label: "Smoothing when moving (One Euro beta)" },
  { key: "activeArea", value: 0.7, min: 0.3, max: 1, step: 0.05, label: "Share of the camera view mapped to the screen" },
  { key: "swapHandedness", value: true, label: "Swap MediaPipe's left/right (unmirrored camera)" },
  { key: "requirePalmFacing", value: true, label: "Open palm must face the camera" },
  // Hand shape
  { key: "fingerExtendedRatio", value: 1.15, min: 1, max: 1.6, step: 0.01, label: "Finger extended: tip/knuckle distance ratio above" },
  { key: "fingerCurledRatio", value: 1.0, min: 0.6, max: 1.2, step: 0.01, label: "Finger curled: tip/knuckle distance ratio below" },
  { key: "thumbTuckedMax", value: 0.4, min: 0.1, max: 0.8, step: 0.01, label: "Thumb tucked: tip within this of the index knuckle" },
  { key: "thumbExtendedMin", value: 0.6, min: 0.3, max: 1.2, step: 0.01, label: "Thumb extended: tip at least this from the index knuckle" },
  { key: "thumbAngleMaxDeg", value: 35, min: 10, max: 60, step: 1, label: "Thumbs up/down: degrees from vertical" },
  { key: "pinchOn", value: 0.25, min: 0.1, max: 0.5, step: 0.01, label: "Pinch: thumb-index distance below" },
  { key: "pinchOff", value: 0.35, min: 0.15, max: 0.7, step: 0.01, label: "Pinch ends: thumb-index distance above" },
  { key: "pinchMinReach", value: 0.8, min: 0.4, max: 1.4, step: 0.01, label: "Pinch: index tip at least this far from the wrist (not a fist)" },
  // Timing
  { key: "armHoldMs", value: 500, min: 100, max: 2000, step: 50, label: "Arm: hold a still open palm" },
  { key: "armStillSpeed", value: 0.5, min: 0.1, max: 3, step: 0.1, label: "Arm: wrist speed below" },
  { key: "autoDisarmMs", value: 6000, min: 1000, max: 30000, step: 500, label: "Disarm after this long with no hand" },
  { key: "tapMaxMs", value: 300, min: 100, max: 800, step: 10, label: "Pinch tap: released within" },
  { key: "tapCooldownMs", value: 250, min: 0, max: 1500, step: 10, label: "Pinch tap cooldown" },
  { key: "secondHandWaitMs", value: 200, min: 0, max: 600, step: 10, label: "Wait this long for a second pinching hand" },
  { key: "dragHoldMs", value: 300, min: 100, max: 1000, step: 10, label: "Pinch held this long starts a drag" },
  { key: "spreadRatio", value: 1.4, min: 1.1, max: 3, step: 0.05, label: "Two-hand spread: distance grows by this factor" },
  { key: "squeezeRatio", value: 0.6, min: 0.2, max: 0.95, step: 0.05, label: "Two-hand squeeze: distance shrinks to this factor" },
  { key: "fistHoldMs", value: 400, min: 100, max: 2000, step: 50, label: "Fist hold" },
  { key: "fistCooldownMs", value: 800, min: 0, max: 3000, step: 50, label: "Fist cooldown" },
  { key: "thumbHoldMs", value: 600, min: 100, max: 2000, step: 50, label: "Thumbs up/down hold" },
  { key: "thumbCooldownMs", value: 1000, min: 0, max: 3000, step: 50, label: "Thumbs up/down cooldown" },
  { key: "swipeSpeed", value: 2, min: 0.5, max: 15, step: 0.25, label: "Swipe: wrist speed above" },
  { key: "swipeDominance", value: 2, min: 1, max: 5, step: 0.25, label: "Swipe: main direction this many times the other" },
  { key: "velocityWindowMs", value: 150, min: 50, max: 500, step: 10, label: "Measure speed over this window" },
  { key: "swipeSideCooldownMs", value: 600, min: 0, max: 3000, step: 50, label: "Swipe left/right cooldown" },
  { key: "swipeDownCooldownMs", value: 800, min: 0, max: 3000, step: 50, label: "Swipe down cooldown" },
  { key: "swipeAfterReleaseMs", value: 300, min: 0, max: 1500, step: 10, label: "Ignore swipes this long after a pinch ends" },
];

export function defaultSettings() {
  return Object.fromEntries(SETTINGS.map((s) => [s.key, s.value]));
}
