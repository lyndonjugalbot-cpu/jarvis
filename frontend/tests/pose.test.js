import assert from "node:assert/strict";
import { test } from "node:test";

import { OneEuroFilter } from "../src/gestures/filters.js";
import { classify, measure, trueHandedness } from "../src/gestures/pose.js";
import { defaultSettings } from "../src/gestures/settings.js";
import { place } from "../src/gestures/synth.js";

const S = defaultSettings();
const ASPECT = 4 / 3;
const POSES = ["open_palm", "fist", "point", "pinch", "thumbs_up", "thumbs_down"];

function poseOf(spec, settings = S) {
  const raw = place(spec, ASPECT);
  const hand = trueHandedness(raw.handedness, settings);
  return classify(measure(raw.landmarks, ASPECT, hand, settings), settings);
}

for (const pose of POSES) {
  test(`${pose} is recognized at any size, position, tilt and hand`, () => {
    for (const hand of ["Right", "Left"]) {
      for (const size of [0.08, 0.18, 0.3]) {
        for (const rotate of [-20, 0, 20]) {
          for (const [x, y] of [[0.3, 0.4], [0.7, 0.7]]) {
            assert.equal(poseOf({ pose, hand, size, rotate, x, y }), pose, `${hand} ${size} ${rotate}deg`);
          }
        }
      }
    }
  });
}

test("the back of an open hand is not an open palm unless allowed", () => {
  assert.equal(poseOf({ pose: "open_palm", back: true }), "other");
  assert.equal(poseOf({ pose: "open_palm", back: true }, { ...S, requirePalmFacing: false }), "open_palm");
});

test("MediaPipe's labels are swapped for the unmirrored camera frame", () => {
  assert.equal(trueHandedness("Left", S), "Right");
  assert.equal(trueHandedness("Left", { ...S, swapHandedness: false }), "Left");
});

test("one euro filter steadies jitter but follows real moves", () => {
  const f = new OneEuroFilter({ minCutoff: 1.5, beta: 8 });
  let maxJitter = 0;
  for (let i = 0; i < 60; i++) {
    const v = f.filter(0.5 + (i % 2 ? 0.004 : -0.004), i * 33);
    if (i > 10) maxJitter = Math.max(maxJitter, Math.abs(v - 0.5));
  }
  assert.ok(maxJitter < 0.002, `jitter ${maxJitter}`);
  let v = 0;
  for (let i = 60; i < 75; i++) v = f.filter(0.9, i * 33);
  assert.ok(v > 0.88, `follows a step: ${v}`);
});
