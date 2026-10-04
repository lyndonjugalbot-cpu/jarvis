import "@fontsource/orbitron/500.css";
import "@fontsource/inter/400.css";
import "./styles/hud.css";

const HEALTH_EVERY_MS = 5000;

function setIndicator(name, state, text = state) {
  const el = document.querySelector(`[data-indicator="${name}"]`);
  el.dataset.state = state;
  el.querySelector(".value").textContent = text;
}

function tickClock() {
  const clock = document.getElementById("clock");
  const now = new Date();
  clock.dateTime = now.toISOString();
  clock.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

async function checkCore() {
  try {
    const res = await fetch("/api/health", { cache: "no-store" });
    const body = res.ok ? await res.json() : null;
    setIndicator("core", body?.status === "ok" ? "online" : "offline");
  } catch {
    setIndicator("core", "offline");
  }
}

tickClock();
setInterval(tickClock, 1000);
checkCore();
setInterval(checkCore, HEALTH_EVERY_MS);
