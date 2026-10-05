import assert from "node:assert/strict";
import { test } from "node:test";

import { replay } from "../src/gestures/engine.js";
import { defaultSettings } from "../src/gestures/settings.js";
import { session } from "../src/gestures/synth.js";

const R = { pose: "open_palm", x: 0.6, y: 0.6, hand: "Right" };
const L = { pose: "open_palm", x: 0.4, y: 0.6, hand: "Left" };
const NOISY = new Set(["cursor", "charge", "drag_move", "two_hand_update"]);

function names(frames, settings) {
  return replay(frames, settings)
    .filter((e) => !NOISY.has(e.type))
    .map((e) => (e.type === "swipe" ? `swipe_${e.direction}` : e.type));
}

// Arm with an open palm where the next gesture starts, so the hand never jumps between frames.
const armed = (at = R) => session().hold(700, { ...at, pose: "open_palm" });
const as = (spec, more) => ({ ...spec, ...more });

test("a still open palm arms after 500 ms, not before", () => {
  assert.deepEqual(names(session().hold(400, R).frames), []);
  assert.deepEqual(names(session().hold(700, R).frames), ["armed"]);
});

test("a moving palm does not arm", () => {
  const s = session().move(1000, [as(R, { x: 0.2 }), as(R, { x: 0.8 })]);
  assert.deepEqual(names(s.frames), []);
});

test("the back of the hand does not arm", () => {
  assert.deepEqual(names(session().hold(1000, as(R, { back: true })).frames), []);
});

test("low-confidence hands are ignored", () => {
  assert.deepEqual(names(session().hold(1000, as(R, { score: 0.3 })).frames), []);
});

test("gestures disarm after 6 s with no hand", () => {
  assert.deepEqual(names(armed().gap(6500).frames), ["armed", "disarmed"]);
});

test("nothing but arming happens while disarmed", () => {
  const s = session()
    .hold(300, as(R, { pose: "pinch" }))
    .hold(600, as(R, { pose: "fist" }))
    .move(200, [as(R, { y: 0.3 }), as(R, { y: 0.8 })]);
  assert.deepEqual(names(s.frames), []);
});

test("a quick pinch is a tap", () => {
  const s = armed().hold(200, as(R, { pose: "pinch" })).hold(300, R);
  assert.deepEqual(names(s.frames), ["armed", "tap"]);
});

test("a two-frame pinch is ignored", () => {
  const s = armed().hold(60, as(R, { pose: "pinch" })).hold(300, R);
  assert.deepEqual(names(s.frames), ["armed"]);
});

test("a held pinch drags", () => {
  const pinch = as(R, { pose: "pinch", x: 0.5 });
  const events = replay(armed(pinch).hold(400, pinch).move(500, [pinch, as(pinch, { x: 0.7 })]).hold(300, as(R, { x: 0.7 })).frames);
  const kinds = events.map((e) => e.type);
  assert.deepEqual(
    kinds.filter((k) => !NOISY.has(k)),
    ["armed", "drag_start", "drag_end"],
  );
  const moves = events.filter((e) => e.type === "drag_move");
  assert.ok(moves.length > 5);
  assert.ok(moves.at(-1).x > moves[0].x, "drag follows the hand");
});

test("spreading two pinched hands maximizes", () => {
  const a = as(R, { pose: "pinch", x: 0.58 });
  const b = as(L, { pose: "pinch", x: 0.42 });
  const s = armed(a)
    .hold(200, a, b)
    .move(400, [a, as(a, { x: 0.85 })], [b, as(b, { x: 0.15 })])
    .hold(300, as(R, { x: 0.85 }), as(L, { x: 0.15 }));
  assert.deepEqual(names(s.frames), ["armed", "two_hand_start", "maximize", "two_hand_end"]);
});

test("squeezing two pinched hands restores", () => {
  const a = as(R, { pose: "pinch", x: 0.8 });
  const b = as(L, { pose: "pinch", x: 0.2 });
  const s = armed(a)
    .hold(200, a, b)
    .move(400, [a, as(a, { x: 0.56 })], [b, as(b, { x: 0.44 })])
    .hold(300, as(R, { x: 0.56 }), as(L, { x: 0.44 }));
  assert.deepEqual(names(s.frames), ["armed", "two_hand_start", "restore", "two_hand_end"]);
});

test("a small two-hand change neither maximizes nor restores", () => {
  const a = as(R, { pose: "pinch", x: 0.75 });
  const b = as(L, { pose: "pinch", x: 0.25 });
  const s = armed(a)
    .hold(200, a, b)
    .move(300, [a, as(a, { x: 0.77 })], [b, as(b, { x: 0.23 })])
    .hold(300, as(R, { x: 0.77 }), as(L, { x: 0.23 }));
  assert.deepEqual(names(s.frames), ["armed", "two_hand_start", "two_hand_end"]);
});

// Look-alike pairs from spec section 7.1

test("7.1 a second hand pinching within 200 ms makes a two-hand gesture, not a drag", () => {
  const a = as(R, { pose: "pinch", x: 0.58 });
  const b = as(L, { pose: "pinch", x: 0.42 });
  const s = armed(a)
    .hold(100, a, as(L, { x: 0.42 }))
    .hold(300, a, b)
    .move(300, [a, as(a, { x: 0.85 })], [b, as(b, { x: 0.15 })])
    .hold(300, as(R, { x: 0.85 }), as(L, { x: 0.15 }));
  const got = names(s.frames);
  assert.ok(!got.includes("drag_start"), got.join());
  assert.deepEqual(got, ["armed", "two_hand_start", "maximize", "two_hand_end"]);
});

test("7.1 a second hand joining a drag hands the panel over to a two-hand resize", () => {
  const a = as(R, { pose: "pinch", x: 0.58 });
  const b = as(L, { pose: "pinch", x: 0.42 });
  const s = armed(a)
    .hold(600, a, as(L, { x: 0.42 }))
    .hold(200, a, b)
    .move(300, [a, as(a, { x: 0.85 })], [b, as(b, { x: 0.15 })])
    .hold(300, as(R, { x: 0.85 }), as(L, { x: 0.15 }));
  const events = replay(s.frames);
  const handover = events.find((e) => e.type === "drag_end");
  assert.equal(handover?.handover, true);
  assert.deepEqual(names(s.frames), ["armed", "drag_start", "drag_end", "two_hand_start", "maximize", "two_hand_end"]);
});

test("7.1 a held fist minimizes; a short one does nothing", () => {
  assert.deepEqual(names(armed().hold(600, as(R, { pose: "fist" })).hold(200, R).frames), ["armed", "minimize"]);
  assert.deepEqual(names(armed().hold(250, as(R, { pose: "fist" })).hold(200, R).frames), ["armed"]);
});

test("7.1 a fist that opens into a thumbs-up only confirms", () => {
  const s = armed().hold(300, as(R, { pose: "fist" })).hold(800, as(R, { pose: "thumbs_up" })).hold(200, R);
  assert.deepEqual(names(s.frames), ["armed", "confirm"]);
});

test("thumbs down cancels", () => {
  assert.deepEqual(names(armed().hold(800, as(R, { pose: "thumbs_down" })).frames), ["armed", "cancel"]);
});

test("a hold fires once however long it lasts", () => {
  assert.deepEqual(names(armed().hold(3000, as(R, { pose: "fist" })).frames), ["armed", "minimize"]);
});

test("open-palm swipes go left, right and down", () => {
  const right = armed(as(R, { x: 0.3 })).move(150, [as(R, { x: 0.3 }), as(R, { x: 0.7 })]).hold(200, as(R, { x: 0.7 }));
  assert.deepEqual(names(right.frames), ["armed", "swipe_right"]);
  const left = armed(as(R, { x: 0.7 })).move(150, [as(R, { x: 0.7 }), as(R, { x: 0.3 })]).hold(200, as(R, { x: 0.3 }));
  assert.deepEqual(names(left.frames), ["armed", "swipe_left"]);
  const down = armed(as(R, { y: 0.3 })).move(200, [as(R, { y: 0.3 }), as(R, { y: 0.8 })]).hold(200, as(R, { y: 0.8 }));
  assert.deepEqual(names(down.frames), ["armed", "swipe_down"]);
});

test("7.1 a fast downward palm while disarmed neither arms nor swipes", () => {
  const s = session().move(250, [as(R, { y: 0.25 }), as(R, { y: 0.85 })]).hold(300, as(R, { y: 0.85 }));
  assert.deepEqual(names(s.frames), []);
});

test("7.1 letting go of a dragged panel does not flick it away", () => {
  const pinch = as(R, { pose: "pinch", x: 0.5 });
  const s = armed(pinch)
    .hold(500, pinch)
    .move(150, [as(R, { x: 0.5 }), as(R, { x: 0.8 })]);
  assert.deepEqual(names(s.frames), ["armed", "drag_start", "drag_end"]);
});

test("pointing only moves the cursor", () => {
  const point = as(R, { pose: "point" });
  const events = replay(armed(point).move(1000, [point, as(point, { x: 0.4 })]).frames);
  assert.deepEqual(
    events.filter((e) => !NOISY.has(e.type)).map((e) => e.type),
    ["armed"],
  );
  assert.ok(events.filter((e) => e.type === "cursor" && e.armed).length > 20);
});

test("thresholds come from the settings object", () => {
  const settings = { ...defaultSettings(), armHoldMs: 1500 };
  assert.deepEqual(names(session().hold(1000, R).frames, settings), []);
});

test("the HUD demo script performs every gesture once", async () => {
  const { buildDemo } = await import("../src/gestures/demo.js");
  const frames = buildDemo({ welcome: { x: 0.33, y: 0.42 }, settings: defaultSettings() });
  assert.deepEqual(names(frames), [
    "armed",
    "drag_start",
    "drag_end",
    "two_hand_start",
    "maximize",
    "two_hand_end",
    "two_hand_start",
    "restore",
    "two_hand_end",
    "minimize",
    "swipe_right",
  ]);
});
