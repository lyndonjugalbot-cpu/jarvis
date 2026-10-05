import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { createController } from "../src/gestures/controller.js";
import { BUILTINS, buildBuiltin } from "../src/hud/holograms/builtins.js";
import { explodeVectors, fitScale, reach, spreadToExplode } from "../src/hud/holograms/explode.js";

test("spreading two hands breaks the model apart; squeezing puts it back", () => {
  assert.equal(spreadToExplode(0, 1), 0);
  assert.ok(Math.abs(spreadToExplode(0, 1.3) - 0.5) < 1e-9);
  assert.equal(spreadToExplode(0, 2), 1); // capped
  assert.equal(spreadToExplode(1, 0.65), 0); // a full squeeze from fully apart
  assert.ok(spreadToExplode(1, 0.9) < 1 && spreadToExplode(1, 0.9) > 0.5);
  assert.equal(spreadToExplode(0.4, Number.NaN), 0.4);
});

test("file parts move straight out from the center, center parts up and down", () => {
  const [right, left, middle, alsoMiddle] = explodeVectors(
    [
      [2, 0, 0],
      [-1, 0, 0],
      [0, 0, 0],
      [0, 0, 0],
    ],
    [0, 0, 0],
    2,
  );
  assert.ok(right[0] > 2 * 0.9 && right[1] === 0);
  assert.ok(left[0] < -0.9);
  assert.ok(middle[1] > 0 && alsoMiddle[1] < 0);
});

test("the model is drawn smaller as it breaks apart, so it stays on the stage", () => {
  const boxes = [
    { min: [-1, -1, -1], max: [1, 1, 1] },
    { min: [1, -0.5, -0.5], max: [2, 0.5, 0.5] },
  ];
  const offsets = [
    [0, 0, 0],
    [3, 0, 0],
  ];
  const assembled = reach(boxes, offsets, 0, [0, 0, 0]);
  const exploded = reach(boxes, offsets, 1, [0, 0, 0]);
  assert.ok(exploded > assembled + 2.9);
  assert.equal(fitScale(1, assembled, exploded, 0), 1 / assembled);
  assert.ok(fitScale(1, assembled, exploded, 1) < fitScale(1, assembled, exploded, 0.5));
});

test("every built-in model builds, with named, described parts that move apart", () => {
  for (const { id } of BUILTINS) {
    const model = buildBuiltin(id);
    const names = model.parts.map((p) => p.name);
    assert.equal(new Set(names).size, names.length, `${id}: part names repeat`);
    for (const part of model.parts) {
      assert.ok(part.info.length > 20, `${id}/${part.name}: no description`);
      assert.ok(part.geometry.attributes.position.count > 0);
    }
    const boxes = model.parts.map((p) => {
      p.geometry.computeBoundingBox();
      return { min: p.geometry.boundingBox.min.toArray(), max: p.geometry.boundingBox.max.toArray() };
    });
    const offsets = model.parts.map((p) => p.explode);
    assert.ok(reach(boxes, offsets, 1, [0, 0, 0]) > reach(boxes, offsets, 0, [0, 0, 0]) * 1.3, id);
  }
});

test("the built-in ids match the ones JARVIS can ask for", () => {
  const source = readFileSync(new URL("../../backend/tools/hud.py", import.meta.url), "utf8");
  const block = source.slice(source.indexOf("BUILTIN_MODELS = {"), source.indexOf("}", source.indexOf("BUILTIN_MODELS = {")));
  const backend = [...block.matchAll(/"([a-z-]+)": "([^"]+)"/g)].map(([, id, title]) => ({ id, title }));
  assert.deepEqual(
    backend,
    BUILTINS.map(({ id, title }) => ({ id, title })),
  );
});

// ---------------------------------------------------------------- gestures on the model

globalThis.document ??= { elementFromPoint: () => null };
globalThis.window ??= { innerWidth: 1000, innerHeight: 800 };

function fakes({ panelAt = null } = {}) {
  const log = [];
  const panels = {
    focused: null,
    hit: (x, y) => (panelAt && x < 0.3 ? panelAt : null),
    hover: () => {},
    grab: (p) => log.push(["grab", p.title]),
    dragTo: () => {},
    release: () => {},
    maximize: (p) => log.push(["maximize", p.title]),
    restore: () => {},
    minimize: () => {},
    focus: () => {},
    cycleFocus: () => null,
  };
  const model = {
    active: true,
    title: "Jet engine",
    explode: 0,
    contains: (x) => x >= 0.3 && x <= 0.7,
    hit: () => ({ name: "Fan" }),
    hover: () => {},
    select: (part) => (log.push(["select", part?.name]), part),
    setExplode(t) {
      this.explode = t;
      log.push(["explode", Number(t.toFixed(2))]);
    },
    beginTurn: () => log.push(["turn start"]),
    turnTo: () => log.push(["turn"]),
    endTurn: () => log.push(["turn end"]),
    close() {
      this.active = false;
      log.push(["close"]);
    },
    cycle: async () => "Drone",
  };
  const said = [];
  const controller = createController({
    panels,
    model,
    cursor: { move: () => {}, charge: () => {} },
    settings: { activeArea: 1 },
    say: (text) => said.push(text),
    setIndicator: () => {},
  });
  const at = (x, y = 0.5) => ({ type: "cursor", x, y, armed: true });
  return { log, said, model, controller, at };
}

test("two hands pull the model apart instead of maximizing a panel", () => {
  const { log, said, model, controller } = fakes();
  controller.handle([
    { type: "two_hand_start", x: 0.5, y: 0.5 },
    { type: "two_hand_update", ratio: 1.3 },
    { type: "maximize" },
    { type: "two_hand_update", ratio: 1.8 },
    { type: "two_hand_end" },
  ]);
  assert.equal(model.explode, 1);
  assert.deepEqual(log, [
    ["explode", 0.5],
    ["explode", 1],
  ]);
  assert.match(said.at(-1), /broken apart/);
});

test("over the model a pinch-drag turns it and a pinch picks a part", () => {
  const { log, controller, at } = fakes();
  controller.handle([at(0.5), { type: "drag_start" }, { type: "drag_move", x: 0.55, y: 0.5 }, { type: "drag_end" }]);
  controller.handle([at(0.5), { type: "tap" }]);
  assert.deepEqual(log, [["turn start"], ["turn"], ["turn end"], ["select", "Fan"]]);
});

test("a fist puts the model back together, then puts it away", () => {
  const { log, model, controller, at } = fakes();
  model.explode = 0.8;
  controller.handle([at(0.5), { type: "minimize" }]);
  assert.equal(model.explode, 0);
  controller.handle([{ type: "minimize" }]);
  assert.equal(model.active, false);
  assert.deepEqual(log.at(-1), ["close"]);
});

test("panels still come first", () => {
  const { log, controller, at } = fakes({ panelAt: { title: "Weather" } });
  controller.handle([at(0.1), { type: "drag_start" }]);
  controller.handle([{ type: "two_hand_start", x: 0.1, y: 0.5 }, { type: "two_hand_update", ratio: 1.8 }, { type: "maximize" }]);
  assert.deepEqual(log, [
    ["grab", "Weather"],
    ["maximize", "Weather"],
  ]);
});
