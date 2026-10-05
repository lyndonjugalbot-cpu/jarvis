// Status bar indicators (gestures, fps, mic, core, brain), the clock and the date.

function indicator(name) {
  return document.querySelector(`[data-indicator="${name}"]`);
}

export function setIndicator(name, state, text = state, sub) {
  const el = indicator(name);
  if (!el) return;
  el.dataset.state = state;
  el.querySelector(".value").textContent = text;
  if (sub !== undefined) el.querySelector(".sub").textContent = sub;
}

export function setIndicatorLabel(name, text) {
  const label = indicator(name)?.querySelector(".label");
  if (label) label.textContent = text;
}

export function startClock(clockEl, dateEl) {
  const tick = () => {
    const now = new Date();
    clockEl.dateTime = now.toISOString();
    clockEl.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    dateEl.textContent = now.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short", year: "numeric" });
  };
  tick();
  setInterval(tick, 1000);
}
