// Replays real webcam sessions recorded in the HUD (press R to start and stop recording).
// Save a recording as tests/recordings/<name>.json and add the events it should produce:
// { "expect": ["armed", "drag_start", "drag_end"], "frames": [...] }

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";

import { replay } from "../src/gestures/engine.js";

const DIR = new URL("./recordings/", import.meta.url);
const NOISY = new Set(["cursor", "charge", "drag_move", "two_hand_update"]);

let files = [];
try {
  files = readdirSync(DIR).filter((f) => f.endsWith(".json"));
} catch {
  // no recordings yet
}

for (const file of files) {
  const recording = JSON.parse(readFileSync(new URL(file, DIR), "utf8"));
  test(`recording ${file}`, { skip: !recording.expect && "no expect list yet" }, () => {
    const got = replay(recording.frames)
      .filter((e) => !NOISY.has(e.type))
      .map((e) => (e.type === "swipe" ? `swipe_${e.direction}` : e.type));
    assert.deepEqual(got, recording.expect);
  });
}
