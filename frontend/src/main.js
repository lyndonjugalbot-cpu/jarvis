import "@fontsource/orbitron/500.css";
import "@fontsource/inter/400.css";
import "./styles/hud.css";

import { createController } from "./gestures/controller.js";
import { buildDemo } from "./gestures/demo.js";
import { createGestureEngine } from "./gestures/engine.js";
import { startTracker } from "./gestures/tracker.js";
import { createConfirm } from "./hud/confirm.js";
import { createConversation } from "./hud/conversation.js";
import { createCursor } from "./hud/cursor.js";
import { createDebug } from "./hud/debug.js";
import { drawFrames } from "./hud/frame.js";
import { createGlobe } from "./hud/globe.js";
import { createHologram } from "./hud/hologram.js";
import { createLayout } from "./hud/layout.js";
import { PanelManager } from "./hud/panels.js";
import { createScene } from "./hud/scene.js";
import { createSettingsDrawer, loadSettings } from "./hud/settings-drawer.js";
import { createSounds } from "./hud/sounds.js";
import { setIndicator, setIndicatorLabel, startClock } from "./hud/statusbar.js";
import { createBars, createGauge, createHistory, createRows, createWave } from "./hud/widgets.js";
import { createSocket } from "./net/socket.js";

const $ = (id) => document.getElementById(id);
// Gestures worth telling the core about (for context and the log).
const REPORTED_GESTURES = new Set(["tap", "minimize", "maximize", "restore", "swipe", "confirm", "cancel"]);
const TOAST_MS = 6000;
const WIDGET_FRAME_S = 1 / 30;

const STARTER_PANELS = [
  {
    id: "welcome",
    type: "text",
    title: "Welcome",
    data:
      "Hold up an open palm for half a second to arm gestures. Point to aim, pinch to tap or grab, " +
      "make a fist to minimize, and spread two pinched hands to maximize.",
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
  },
];

// ---------------------------------------------------------------- HUD preferences
const PREFS_KEY = "jarvis.hud";
function loadPrefs() {
  try {
    return { sounds: true, welcome: true, ...JSON.parse(localStorage.getItem(PREFS_KEY) ?? "{}") };
  } catch {
    return { sounds: true, welcome: true };
  }
}
function savePrefs() {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    // storage blocked: preferences last until reload
  }
}
const prefs = loadPrefs();
const sounds = createSounds({ enabled: prefs.sounds });

// ---------------------------------------------------------------- dashboard
drawFrames();
const settings = loadSettings();
const view = createScene($("scene"), $("css-layer"));
const layout = createLayout(view);
const panels = new PanelManager(view, layout, { slot: $("panel-slot"), dock: $("dock") });
const hologram = createHologram(view, layout, $("stage"));
const globe = createGlobe(view, layout, $("globe-slot"), $("globe-label"));
const gauge = createGauge($("gauge"));
const bars = createBars($("bars"), ["Memory", "Disk", "Power", "API spend"]);
const systemRows = createRows($("system-status"));
const moduleRows = createRows($("modules"));
const wave = createWave($("audio-wave"));
const history = createHistory($("analysis"));
const askWave = [...$("ask-wave").children];
startClock($("clock"), $("date"));

if (prefs.welcome) {
  for (const spec of STARTER_PANELS) panels.add(spec);
  panels.focus(panels.find("welcome"));
  prefs.welcome = false; // a clean HUD from the next start; turn them back on in settings (S)
  savePrefs();
}
for (const box of document.querySelectorAll(".hud-settings input")) {
  box.checked = Boolean(prefs[box.name]);
  box.addEventListener("change", () => {
    prefs[box.name] = box.checked;
    if (box.name === "sounds") sounds.enabled = box.checked;
    savePrefs();
  });
}

// What the System status widget shows; filled in by the messages below.
const system = { core: "connecting", memory: null, network: null, camera: false, mic: "off", uptime: null };
const LOOK = {
  online: "online",
  active: "online",
  connected: "online",
  ready: "online",
  listening: "online",
  "wake word": "online",
  stable: "online",
  on: "online",
  standby: "idle",
  connecting: "idle",
  checking: "idle",
  starting: "idle",
  "cooling down": "warn",
  high: "warn",
  offline: "warn",
};
function showSystem() {
  const memory = system.memory == null ? "--" : system.memory < 85 ? "stable" : "high";
  const network = system.network == null ? "checking" : system.network ? "connected" : "offline";
  const audio = { off: "off", starting: "starting", wake: "wake word", listening: "listening", unavailable: "unavailable" };
  const rows = [
    { name: "Core systems", value: system.core },
    { name: "Memory", value: memory },
    { name: "Network", value: network },
    { name: "Camera", value: system.camera ? "on" : "off" },
    { name: "Audio", value: audio[system.mic] ?? system.mic },
  ];
  if (system.uptime != null) rows.push({ name: "Uptime", value: `${system.uptime} h`, look: "online" });
  systemRows.set(rows.map((row) => ({ look: LOOK[row.value] ?? "off", ...row })));
}
showSystem();

// The words beside the hologram light up with what JARVIS is doing.
const MODE = { idle: "monitor", listening: "analyze", thinking: "process", speaking: "assist" };
let voiceState = "idle";
function showMode() {
  const mode = confirmPrompt.pending ? "protect" : (MODE[voiceState] ?? "monitor");
  for (const li of $("stage-modes").children) li.classList.toggle("on", li.dataset.mode === mode);
}

// A one-line note under the stage for HUD feedback (gestures, camera, errors); it fades out.
let toastTimer = 0;
function say(text) {
  const toast = $("toast");
  toast.textContent = text;
  toast.classList.remove("fade");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.add("fade"), TOAST_MS);
}

// ---------------------------------------------------------------- link to the core
const token = import.meta.env.VITE_JARVIS_TOKEN ?? "";
const socket = createSocket({
  url: `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws`,
  token,
  onStatus(status) {
    if (status === "online") setIndicator("core", "online", "online");
    else if (status === "connecting") setIndicator("core", "idle", "connecting");
    else {
      const why = { unauthorized: "token mismatch", forbidden: "refused" }[status] ?? "offline";
      setIndicator("core", "offline", why);
    }
    system.core = status === "online" ? "online" : status === "connecting" ? "connecting" : "offline";
    showSystem();
    if (status === "unauthorized") {
      say(token ? "The core rejected the HUD token. Re-run scripts/setup.sh and restart both." : "No HUD token: run scripts/setup.sh.");
    }
  },
});
const conversation = createConversation({
  messages: $("messages"),
  tags: $("conv-tags"),
  status: $("turn-status"),
  chips: $("turn-chips"),
  form: $("ask"),
  onSubmit(text) {
    if (socket.send("user_text", { text })) return true;
    say("Not connected to the core yet. Start it with scripts/start.sh.");
    return false;
  },
});
const confirmPrompt = createConfirm($("confirm"), {
  onAnswer(actionId, approved) {
    socket.send("confirm", { actionId, approved });
    setTimeout(showMode, 0); // after the prompt has closed
  },
});
showMode();

socket.on("state", ({ state }) => {
  voiceState = state;
  hologram.setState(state);
  conversation.setState(state);
  showMode();
});
socket.on("transcript", ({ role, text, provider, tools, seconds, cost }) => {
  conversation.add(role, text, { provider, tools, seconds, cost });
});
socket.on("error", ({ message }) => say(message));

socket.on("telemetry", ({ cpu, memory, disk, battery, charging, network, uptime_h }) => {
  gauge.set(cpu);
  if (!tracker) history.push(cpu);
  bars.set("Memory", memory, undefined, memory >= 90);
  bars.set("Disk", disk, undefined, disk >= 90);
  if (battery == null) bars.set("Power", 100, "AC");
  else bars.set("Power", battery, `${battery}%${charging ? " +" : ""}`, battery < 20 && !charging);
  Object.assign(system, { memory, network, uptime: uptime_h });
  showSystem();
});
socket.on("modules", ({ rows, home }) => {
  moduleRows.set(rows.map(({ name, state }) => ({ name, value: state, look: LOOK[state] ?? "off" })));
  globe.setHome(home);
});
socket.on("audio", ({ levels }) => {
  wave.push(levels);
  hologram.setLevel(Math.max(...levels, 0));
});

// Microphone: the core listens for "Hey Jarvis"; the Mic indicator and the mic button switch it.
const MIC = {
  off: ["off", "off", ""],
  starting: ["idle", "starting", ""],
  wake: ["online", '"Hey Jarvis"', "active"],
  listening: ["armed", "listening", ""],
  unavailable: ["offline", "unavailable", ""],
};
const micIndicator = document.querySelector('[data-indicator="mic"]');
const micButton = $("mic-button");
let micState = "off";
micButton.dataset.state = "off";
socket.on("mic", ({ state, message }) => {
  micState = state;
  const [look, text, sub] = MIC[state] ?? ["off", state, ""];
  setIndicator("mic", look, text, sub);
  micButton.dataset.state = state;
  micIndicator.title = message || (state === "off" ? "Click to turn the microphone on" : "Click to turn the microphone off");
  micButton.title = micIndicator.title;
  system.mic = state;
  showSystem();
  if (state === "off") wave.clear();
  if (message && state !== "wake") say(message);
});
function toggleMic() {
  if (micState === "unavailable" || micState === "starting") return;
  if (!socket.send("mic", { on: micState === "off" })) say("Not connected to the core yet.");
}
micIndicator.addEventListener("click", toggleMic);
micButton.addEventListener("click", toggleMic);

socket.on("provider", ({ label, paid, coolingDown, order, budget }) => {
  const name = label || order?.[0] || "no provider";
  setIndicator("brain", paid ? "paid" : label ? "online" : "idle", paid ? `${name} | paid` : name);
  document.querySelector('[data-indicator="brain"]').title = coolingDown?.length
    ? `Cooling down: ${coolingDown.join(", ")}`
    : "";
  if (budget) {
    const pct = budget.cap_usd ? (100 * budget.spent_usd) / budget.cap_usd : 0;
    bars.set("API spend", pct, `$${budget.spent_usd.toFixed(2)}`, pct >= 80);
  } else {
    bars.set("API spend", 0, "off");
  }
});
socket.on("show_panel", ({ panel }) => {
  if (!panels.find(panel.id)) sounds.play("open");
  panels.show(panel);
});
socket.on("update_panel", ({ panelId, data }) => {
  const panel = panels.find(panelId);
  if (panel) panels.show({ id: panelId, data });
});
socket.on("close_panel", ({ panelId }) => {
  const panel = panels.find(panelId);
  if (panel) sounds.play("close");
  panels.close(panel);
});
socket.on("confirm_request", (request) => {
  sounds.play("alert");
  confirmPrompt.show(request);
  showMode();
  say("Approve with a thumbs up (or Y), cancel with a thumbs down (or N).");
});
socket.on("confirm_done", ({ actionId }) => {
  confirmPrompt.done(actionId);
  showMode();
});

// Google access was lost (or never set up): offer the browser sign-in on this computer.
const notice = $("notice");
const connectButton = notice.querySelector("button");
socket.on("auth_needed", ({ service, message }) => {
  if (service !== "google") return;
  notice.querySelector(".notice-text").textContent = message;
  notice.hidden = false;
});
connectButton.addEventListener("click", () => {
  if (!socket.send("connect_google")) return;
  connectButton.disabled = true;
  say("Opening Google's sign-in page in your browser...");
});
socket.on("auth_done", ({ ok, message }) => {
  connectButton.disabled = false;
  if (ok) notice.hidden = true;
  say(message);
});

// ---------------------------------------------------------------- gestures
const cursor = createCursor($("cursor"));
const engine = createGestureEngine(settings);
let tracker = null;
let cameraFps = 0;
let replaying = null;
let recording = null;
let mouseDrag = null;

function showGestureState() {
  if (!tracker) return;
  const rate = Math.round(cameraFps);
  const low = rate > 0 && rate < 20;
  setIndicator("gestures", low ? "warn" : engine.armed ? "armed" : "idle", engine.armed ? "armed" : "disarmed");
  document.querySelector('[data-indicator="gestures"]').title = low
    ? `Hand tracking at ${rate} fps: try more light on your hands, or close other heavy apps.`
    : `Hand tracking at ${rate} fps`;
}
setInterval(showGestureState, 1000);

const controller = createController({
  panels,
  cursor,
  settings,
  say,
  setIndicator: (name, state, text) => (name === "gestures" && tracker ? showGestureState() : setIndicator(name, state, text)),
  onConfirm: (approved) => {
    const answered = confirmPrompt.answer(approved);
    showMode();
    return answered;
  },
});
const debug = createDebug($("debug"), $("camera"));
const drawer = createSettingsDrawer($("settings"), settings);
$("conv-menu").addEventListener("click", () => drawer.toggle());

const GESTURE_SOUNDS = { armed: "armed", drag_start: "grab", maximize: "open", restore: "open", minimize: "close" };

function feed(frame, from) {
  const events = engine.update(frame);
  controller.handle(events);
  for (const e of events) {
    if (GESTURE_SOUNDS[e.type]) sounds.play(GESTURE_SOUNDS[e.type]);
    if (e.type === "swipe" && e.direction === "down") sounds.play("close");
  }
  debug.show(frame, engine.hands, events, { fps: cameraFps, armed: engine.armed, source: from });
  for (const e of events) {
    if (!REPORTED_GESTURES.has(e.type)) continue;
    const gesture = e.type === "swipe" ? `swipe_${e.direction}` : e.type;
    socket.send("gesture_event", { gesture, panelId: panels.focused?.id ?? null });
  }
}

// ---------------------------------------------------------------- camera
// While the camera is on, the chart under Audio input shows hand tracking; otherwise CPU history.
function showCamera(on) {
  system.camera = on;
  showSystem();
  $("camera-toggle").textContent = on ? "Stop camera" : "Start camera";
  $("analysis-title").textContent = on ? "Visual analysis" : "CPU history";
  history.reset();
}
showCamera(false);

async function toggleCamera() {
  if (tracker) {
    tracker.stop();
    tracker = null;
    setIndicator("gestures", "off", "camera off");
    showCamera(false);
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
        cameraFps = rate;
        if (replaying) return;
        recording?.push(frame);
        feed(frame, "camera");
      },
    });
    showCamera(true);
    setIndicator("gestures", engine.armed ? "armed" : "idle", engine.armed ? "armed" : "disarmed");
    say("Camera on. Hold up an open palm for half a second to arm gestures.");
  } catch (err) {
    tracker = null;
    setIndicator("gestures", "off", "camera off");
    showCamera(false);
    say(`Couldn't start hand tracking: ${err.message}`);
  }
}
// Hand tracking for the chart: the frame rate, as a share of 60 fps.
setInterval(() => {
  if (tracker) history.push((100 * cameraFps) / 60);
}, 1000);

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
  "/": () => conversation.focus(),
  y: () => {
    confirmPrompt.answer(true);
    showMode();
  },
  c: toggleCamera,
  p: playDemo,
  d: () => debug.toggle(),
  s: () => drawer.toggle(),
  r: toggleRecording,
  "?": () => ($("help").hidden = !$("help").hidden),
  n: () => {
    if (confirmPrompt.answer(false)) {
      showMode();
      return;
    }
    panelCount += 1;
    panels.add({
      id: `note-${panelCount}`,
      title: `Panel ${panelCount}`,
      data: "A new panel. Pinch to grab it, or make a fist to minimize it.",
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
  const action = KEYS[e.key.toLowerCase()];
  if (!action) return;
  e.preventDefault(); // so "/" doesn't land in the text box it focuses
  action();
});
$("camera-toggle").addEventListener("click", toggleCamera);

// ---------------------------------------------------------------- render loop
let last = performance.now();
let widgetClock = 0;
let frames = 0;
let fpsSince = last;
function frame(now) {
  const dt = Math.min((now - last) / 1000, 0.1);
  last = now;
  stepReplay(now);
  panels.update(dt, cursor.position);
  hologram.update(dt, { hidden: Boolean(panels.maximized) });
  globe.update(dt);
  widgetClock += dt;
  if (widgetClock >= WIDGET_FRAME_S) {
    gauge.draw(widgetClock);
    wave.draw(widgetClock);
    history.draw();
    const level = wave.latest();
    askWave.forEach((bar, i) => {
      const height = 20 + Math.min(1, level * (1.6 - Math.abs(i - 2) * 0.3)) * 80;
      bar.style.height = `${Math.round(height)}%`;
    });
    widgetClock = 0;
  }
  view.render();

  frames += 1;
  if (now - fpsSince >= 1000) {
    const fps = Math.round((frames * 1000) / (now - fpsSince));
    setIndicatorLabel("fps", `${fps} fps`);
    const [look, word] = fps >= 50 ? ["online", "stable"] : fps >= 30 ? ["idle", "fair"] : ["warn", "low"];
    setIndicator("fps", look, word);
    frames = 0;
    fpsSince = now;
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

// Dev hooks: replay a recorded session or fake a core message from the console
// (jarvis.socket.emit("show_panel", {...})), or open with ?demo to play the gesture demo.
window.jarvis = { replay, playDemo, panels, engine, settings, view, hologram, globe, socket };
if (new URLSearchParams(window.location.search).has("demo")) setTimeout(playDemo, 800);
