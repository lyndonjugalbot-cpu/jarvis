import "@fontsource/orbitron/500.css";
import "@fontsource/inter/400.css";
import "./styles/hud.css";

import { createController } from "./gestures/controller.js";
import { buildDemo } from "./gestures/demo.js";
import { createGestureEngine } from "./gestures/engine.js";
import { startTracker } from "./gestures/tracker.js";
import { createCursor } from "./hud/cursor.js";
import { createDebug } from "./hud/debug.js";
import { PanelManager } from "./hud/panels.js";
import { createScene } from "./hud/scene.js";
import { createSettingsDrawer, loadSettings } from "./hud/settings-drawer.js";
import { setIndicator, startClock } from "./hud/statusbar.js";

const HEALTH_EVERY_MS = 5000;
const $ = (id) => document.getElementById(id);

const STARTER_PANELS = [
  {
    id: "welcome",
    type: "text",
    title: "Welcome",
    data:
      "Hold up an open palm for half a second to arm gestures. Point to aim, pinch to tap or grab, " +
      "make a fist to minimize, and spread two pinched hands to maximize.",
    position: { x: -2.1, y: 0.55, z: 0 },
  },
  {
    id: "gestures",
    type: "list",
    title: "Gestures",
    data: [
      "Open palm, held: arm",
      "Pinch: tap, or hold to drag",
      "Fist, held: minimize",
      "Two-hand spread / squeeze: maximize / restore",
      "Swipe left or right: change focus",
      "Swipe down: close",
      "Thumbs up / down: confirm / cancel",
    ],
    position: { x: 2.1, y: 0.55, z: 0 },
  },
];

function say(text) {
  $("say").textContent = text;
}

// ---------------------------------------------------------------- HUD
const settings = loadSettings();
const view = createScene($("scene"), $("css-layer"));
const panels = new PanelManager(view, $("dock"));
for (const spec of STARTER_PANELS) panels.add(spec);
panels.focus(panels.panels[0]);

const cursor = createCursor($("cursor"));
const engine = createGestureEngine(settings);
const controller = createController({ panels, cursor, settings, say, setIndicator });
const debug = createDebug($("debug"), $("camera"));
const drawer = createSettingsDrawer($("settings"), settings);
startClock($("clock"));

let tracker = null;
let source = "none";
let fps = 0;
let replaying = null;
let recording = null;
let mouseDrag = null;

function feed(frame, from) {
  const events = engine.update(frame);
  controller.handle(events);
  debug.show(frame, engine.hands, events, { fps, armed: engine.armed, source: from });
}

// ---------------------------------------------------------------- camera
async function toggleCamera() {
  if (tracker) {
    tracker.stop();
    tracker = null;
    source = "none";
    setIndicator("gestures", "off", "camera off");
    $("camera-toggle").textContent = "Start camera";
    say("Camera off.");
    return;
  }
  setIndicator("gestures", "idle", "starting");
  say("Starting the camera and hand tracking...");
  try {
    tracker = await startTracker({
      video: $("camera"),
      settings,
      onFrame(frame, rate) {
        fps = rate;
        if (replaying) return;
        recording?.push(frame);
        feed(frame, "camera");
      },
    });
    source = "camera";
    $("camera-toggle").textContent = "Stop camera";
    setIndicator("gestures", engine.armed ? "armed" : "idle", engine.armed ? "armed" : "disarmed");
    say("Camera on. Hold up an open palm for half a second to arm gestures.");
  } catch (err) {
    tracker = null;
    setIndicator("gestures", "off", "camera off");
    say(`Couldn't start hand tracking: ${err.message}`);
  }
}

// ---------------------------------------------------------------- replay, demo, recording
function replay(frames) {
  if (!frames?.length) return;
  replaying = { frames, i: 0, start: performance.now(), t0: frames[0].t };
}

function stepReplay(now) {
  if (!replaying) return;
  const r = replaying;
  while (r.i < r.frames.length && r.frames[r.i].t - r.t0 <= now - r.start) {
    const frame = r.frames[r.i];
    feed({ ...frame, t: r.start + (frame.t - r.t0) }, "replay");
    r.i += 1;
  }
  if (r.i >= r.frames.length) replaying = null;
}

function playDemo() {
  for (const p of [...panels.panels]) {
    if (p.state === "minimized") panels.unminimize(p);
  }
  if (!panels.find("welcome")) panels.add(STARTER_PANELS[0]);
  const welcome = panels.find("welcome");
  panels.restore(welcome);
  const aspect = window.innerWidth / window.innerHeight;
  debug.toggle(true);
  say("Demo: synthetic hands are driving the real gesture engine.");
  replay(buildDemo({ welcome: view.screenOf(welcome.home), settings, aspect }));
}

function toggleRecording() {
  if (!tracker) {
    say("Start the camera (C) before recording.");
    return;
  }
  if (!recording) {
    recording = [];
    say("Recording hand landmarks. Press R again to stop and save.");
    return;
  }
  const blob = new Blob([JSON.stringify({ recordedAt: new Date().toISOString(), frames: recording })], {
    type: "application/json",
  });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `gesture-session-${Date.now()}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
  say(`Saved ${recording.length} frames. Add an "expect" list and drop it in frontend/tests/recordings/.`);
  recording = null;
}

// ---------------------------------------------------------------- mouse and keyboard
const canvas = $("scene");
const toUnit = (e) => ({ x: e.clientX / window.innerWidth, y: e.clientY / window.innerHeight });

canvas.addEventListener("pointerdown", (e) => {
  const p = toUnit(e);
  const panel = panels.hit(p.x, p.y);
  if (!panel) return;
  mouseDrag = panel;
  panels.grab(panel, p.x, p.y);
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener("pointermove", (e) => {
  const p = toUnit(e);
  if (mouseDrag) panels.dragTo(mouseDrag, p.x, p.y);
  else if (!tracker && !replaying) panels.hover(panels.hit(p.x, p.y));
});
canvas.addEventListener("pointerup", () => {
  panels.release(mouseDrag);
  mouseDrag = null;
});
canvas.addEventListener("dblclick", (e) => {
  const p = toUnit(e);
  const panel = panels.hit(p.x, p.y);
  if (!panel) return;
  if (panel.state === "maximized") panels.restore(panel);
  else panels.maximize(panel);
});

let panelCount = 0;
const KEYS = {
  c: toggleCamera,
  p: playDemo,
  d: () => debug.toggle(),
  s: () => drawer.toggle(),
  r: toggleRecording,
  "?": () => ($("help").hidden = !$("help").hidden),
  n: () => {
    panelCount += 1;
    panels.add({
      id: `note-${panelCount}`,
      title: `Panel ${panelCount}`,
      data: "A new panel. Pinch to grab it, or make a fist to minimize it.",
      position: { x: (Math.random() - 0.5) * 4, y: (Math.random() - 0.5) * 2, z: 0 },
    });
  },
  arrowright: () => panels.cycleFocus(1),
  arrowleft: () => panels.cycleFocus(-1),
  m: () => panels.minimize(panels.focused),
  x: () => panels.close(panels.focused),
  f: () => {
    const panel = panels.focused;
    if (!panel) return;
    if (panel.state === "maximized") panels.restore(panel);
    else panels.maximize(panel);
  },
};
window.addEventListener("keydown", (e) => {
  if (e.target.closest?.("input, textarea") || e.metaKey || e.ctrlKey || e.altKey) return;
  KEYS[e.key.toLowerCase()]?.();
});
$("camera-toggle").addEventListener("click", toggleCamera);

// ---------------------------------------------------------------- core health
async function checkCore() {
  try {
    const res = await fetch("/api/health", { cache: "no-store" });
    const body = res.ok ? await res.json() : null;
    setIndicator("core", body?.status === "ok" ? "online" : "offline");
  } catch {
    setIndicator("core", "offline");
  }
}
checkCore();
setInterval(checkCore, HEALTH_EVERY_MS);

// ---------------------------------------------------------------- render loop
let last = performance.now();
function frame(now) {
  const dt = Math.min((now - last) / 1000, 0.1);
  last = now;
  stepReplay(now);
  panels.update(dt, cursor.position);
  view.render();
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

// Dev hooks: replay a recorded session from the console, or open with ?demo to play the demo.
window.jarvis = { replay, playDemo, panels, engine, settings, view };
if (new URLSearchParams(window.location.search).has("demo")) setTimeout(playDemo, 800);
