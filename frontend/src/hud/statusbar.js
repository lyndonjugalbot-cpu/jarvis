// Status bar indicators: gestures, mic, core connection, brain provider, plus the clock.

export function setIndicator(name, state, text = state) {
  const el = document.querySelector(`[data-indicator="${name}"]`);
  if (!el) return;
  el.dataset.state = state;
  el.querySelector(".value").textContent = text;
}

export function startClock(el) {
  const tick = () => {
    const now = new Date();
    el.dateTime = now.toISOString();
    el.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };
  tick();
  setInterval(tick, 1000);
}
