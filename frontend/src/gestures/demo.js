// A scripted demo (press P): synthetic hands replayed through the real gesture engine, aimed at
// the panels where they are on screen right now. Arm, grab and move a panel, spread to maximize,
// squeeze to restore, fist to minimize, swipe to change focus.

import { handSpace, session } from "./synth.js";

const SIZE = 0.16;

export function buildDemo({ welcome, settings, aspect = 16 / 9 }) {
  const margin = (1 - settings.activeArea) / 2;

  // A hand whose fingertip (or pinch point) lands on `screen`. synth positions the wrist.
  function aim(pose, screen, which = "Right") {
    const { points } = handSpace(pose);
    const [ox, oy] =
      pose === "pinch"
        ? [(points[4][0] + points[8][0]) / 2, (points[4][1] + points[8][1]) / 2]
        : points[8];
    const flip = which === "Left" ? -1 : 1;
    return {
      pose,
      hand: which,
      size: SIZE,
      x: screen.x * settings.activeArea + margin - (flip * ox * SIZE) / aspect,
      y: screen.y * settings.activeArea + margin + oy * SIZE,
    };
  }
  // The same hand in a new pose: the wrist stays put, as it does when real fingers move.
  const as = (spec, pose) => ({ ...spec, pose });
  const shift = (spec, dx, dy = 0) => ({ ...spec, x: spec.x + dx, y: spec.y + dy });

  const mid = { x: 0.45, y: 0.5 };
  const start = aim("point", { x: 0.62, y: 0.72 });
  const onWelcome = aim("pinch", welcome);
  const moved = aim("pinch", mid);
  const r1 = aim("pinch", { x: mid.x + 0.06, y: mid.y });
  const l1 = aim("pinch", { x: mid.x - 0.06, y: mid.y }, "Left");
  const r2 = aim("pinch", { x: mid.x + 0.32, y: mid.y });
  const l2 = aim("pinch", { x: mid.x - 0.32, y: mid.y }, "Left");

  const s = session({ aspect });
  s.hold(900, as(start, "open_palm")) // arm
    .hold(250, start)
    .move(700, [start, aim("point", welcome)])
    .hold(300, aim("point", welcome))
    .hold(450, onWelcome) // grab
    .move(900, [onWelcome, moved])
    .hold(400, as(moved, "point")) // let go
    .hold(250, r1, l1)
    .move(700, [r1, r2], [l1, l2])
    .hold(900, as(r2, "open_palm"), as(l2, "open_palm")) // maximize
    .hold(250, r2, l2)
    .move(700, [r2, r1], [l2, l1])
    .hold(700, as(r1, "open_palm"), as(l1, "open_palm")) // restore
    .hold(800, as(r1, "fist")) // minimize
    .hold(400, as(r1, "open_palm"))
    .move(1000, [as(r1, "open_palm"), shift(as(r1, "open_palm"), -0.12, 0.08)]) // slow: no swipe
    .hold(300, shift(as(r1, "open_palm"), -0.12, 0.08))
    .move(150, [shift(as(r1, "open_palm"), -0.12, 0.08), shift(as(r1, "open_palm"), 0.28, 0.08)]) // swipe
    .hold(600, shift(as(r1, "open_palm"), 0.28, 0.08))
    .gap(200);
  return s.frames;
}
