// Landmark frames in, gesture events out. A frame is
// { t, aspect, hands: [{ handedness, score, landmarks }] } with mirrored, smoothed landmarks.

import { createArbiter } from "./arbiter.js";
import { createRecognizer } from "./recognizer.js";
import { defaultSettings } from "./settings.js";

export function createGestureEngine(settings = defaultSettings()) {
  const recognizer = createRecognizer(settings);
  const arbiter = createArbiter(settings);
  let hands = [];

  return {
    settings,
    update(frame) {
      hands = recognizer.update(frame);
      return arbiter.update(frame.t, hands, frame.aspect);
    },
    get hands() {
      return hands;
    },
    get armed() {
      return arbiter.armed;
    },
  };
}

// Run a whole recorded session and return every event (for tests and replays).
export function replay(frames, settings) {
  const engine = createGestureEngine(settings);
  return frames.flatMap((frame) => engine.update(frame));
}
