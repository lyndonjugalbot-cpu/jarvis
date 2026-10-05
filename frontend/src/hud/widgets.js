// The dashboard's small instruments (HUD.png): the CPU gauge, level bars, status rows, the audio
// waveform and the history chart. Canvases are drawn at the screen's pixel density.

const CYAN = "#22d3ee";
const BRIGHT = "#7ff3ff";
const FAINT = "rgba(34, 211, 238, 0.18)";

function fit(canvas) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

// ---------------------------------------------------------------- CPU gauge (radar style)
export function createGauge(canvas, { label = "CPU" } = {}) {
  let value = 0;
  let shown = 0;
  let t = 0;
  return {
    set(v) {
      value = Math.max(0, Math.min(100, Number(v) || 0));
    },
    draw(dt) {
      t += dt;
      shown += (value - shown) * Math.min(1, dt * 4);
      const { ctx, w, h } = fit(canvas);
      const cx = w / 2;
      const cy = h / 2;
      const R = Math.min(w, h) / 2 - 4;
      ctx.lineWidth = 1;
      ctx.strokeStyle = FAINT;
      for (const r of [R, R * 0.72, R * 0.42]) {
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.setLineDash([2, 5]);
      ctx.beginPath();
      ctx.arc(cx, cy, R * 0.86, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(cx - R, cy);
      ctx.lineTo(cx + R, cy);
      ctx.moveTo(cx, cy - R);
      ctx.lineTo(cx, cy + R);
      ctx.stroke();
      // ticks
      for (let i = 0; i < 60; i += 1) {
        const a = (i / 60) * Math.PI * 2;
        const inner = i % 5 ? R * 0.94 : R * 0.9;
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(a) * inner, cy + Math.sin(a) * inner);
        ctx.lineTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R);
        ctx.stroke();
      }
      // the load arc, from the top clockwise
      const start = -Math.PI / 2;
      ctx.lineWidth = 4;
      ctx.lineCap = "round";
      ctx.strokeStyle = shown > 85 ? "#f59e0b" : BRIGHT;
      ctx.shadowColor = CYAN;
      ctx.shadowBlur = 10;
      ctx.beginPath();
      ctx.arc(cx, cy, R * 0.72, start, start + (Math.max(shown, 1) / 100) * Math.PI * 2);
      ctx.stroke();
      // a sweep, like a radar
      const sweep = (t * 1.2) % (Math.PI * 2);
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = "rgba(127, 243, 255, 0.5)";
      ctx.beginPath();
      ctx.arc(cx, cy, R * 0.86, sweep, sweep + 0.6);
      ctx.stroke();
      ctx.shadowBlur = 14;
      ctx.fillStyle = BRIGHT;
      ctx.beginPath();
      ctx.arc(cx, cy, 5 + Math.sin(t * 3) * 1, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.textAlign = "center";
      ctx.fillStyle = BRIGHT;
      ctx.font = `500 ${Math.round(R * 0.2)}px Orbitron, sans-serif`;
      ctx.fillText(`${Math.round(shown)}%`, cx, cy + R * 0.3);
      ctx.fillStyle = "rgba(190, 232, 248, 0.6)";
      ctx.font = `${Math.round(R * 0.1)}px Orbitron, sans-serif`;
      ctx.fillText(label, cx, cy - R * 0.2);
    },
  };
}

// ---------------------------------------------------------------- level bars
export function createBars(el, names) {
  const bars = new Map();
  for (const name of names) {
    const row = document.createElement("div");
    row.className = "bar";
    const label = document.createElement("span");
    label.textContent = name;
    const value = document.createElement("span");
    value.textContent = "--";
    const track = document.createElement("div");
    track.className = "track";
    const fill = document.createElement("div");
    fill.className = "fill";
    track.append(fill);
    row.append(label, value, track);
    el.append(row);
    bars.set(name, { row, value, fill });
  }
  return {
    // pct: 0..100 (or null for none); text: what to print; warn: amber
    set(name, pct, text, warn = false) {
      const bar = bars.get(name);
      if (!bar) return;
      bar.value.textContent = text ?? (pct == null ? "--" : `${Math.round(pct)}%`);
      bar.fill.style.width = `${Math.max(0, Math.min(100, pct ?? 0))}%`;
      bar.row.classList.toggle("warn", warn);
    },
  };
}

// ---------------------------------------------------------------- status rows
// rows: [{ name, value, look }] where look is online | idle | warn | off
export function createRows(dl) {
  return {
    set(rows) {
      const nodes = [];
      for (const { name, value, look = "online" } of rows) {
        const dot = document.createElement("span");
        dot.className = "dot";
        dot.dataset.state = look;
        const dt = document.createElement("dt");
        const label = document.createElement("span");
        label.textContent = name;
        dt.append(dot, label);
        const dd = document.createElement("dd");
        dd.textContent = value;
        if (look === "off") dd.className = "muted";
        if (look === "warn") dd.className = "warn";
        nodes.push(dt, dd);
      }
      dl.replaceChildren(...nodes);
    },
  };
}

// ---------------------------------------------------------------- audio waveform
// Newest sound on the right; quiet stays a dotted line, like HUD.png.
export function createWave(canvas, { length = 96 } = {}) {
  const levels = new Array(length).fill(0);
  let pending = [];
  let carry = 0;
  return {
    push(values) {
      pending.push(...values);
    },
    clear() {
      levels.fill(0);
      pending = [];
    },
    latest() {
      return levels[levels.length - 1];
    },
    draw(dt) {
      // About 30 samples a second scroll in; the mic sends levels in small batches.
      carry += dt * 30;
      while (carry >= 1) {
        carry -= 1;
        levels.shift();
        levels.push(pending.length ? pending.shift() : 0);
      }
      if (pending.length > 30) pending = pending.slice(-30);
      const { ctx, w, h } = fit(canvas);
      const mid = h / 2;
      const step = w / length;
      ctx.fillStyle = "rgba(34, 211, 238, 0.45)";
      for (let x = 0; x < w; x += 4) ctx.fillRect(x, mid - 0.5, 2, 1);
      ctx.strokeStyle = BRIGHT;
      ctx.shadowColor = CYAN;
      ctx.shadowBlur = 6;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      levels.forEach((level, i) => {
        const amp = Math.max(level, 0.02) * (h / 2 - 2);
        const x = i * step + step / 2;
        ctx.moveTo(x, mid - amp);
        ctx.lineTo(x, mid + amp);
      });
      ctx.stroke();
      ctx.shadowBlur = 0;
    },
  };
}

// ---------------------------------------------------------------- history area chart
export function createHistory(canvas, { length = 60 } = {}) {
  const series = [];
  return {
    push(value) {
      series.push(Math.max(0, Math.min(100, Number(value) || 0)));
      if (series.length > length) series.shift();
    },
    reset() {
      series.length = 0;
    },
    draw() {
      const { ctx, w, h } = fit(canvas);
      ctx.strokeStyle = FAINT;
      ctx.lineWidth = 1;
      for (const y of [h * 0.33, h * 0.66]) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }
      if (series.length < 2) return;
      const x = (i) => (i / (length - 1)) * w + (length - series.length) * (w / (length - 1));
      const y = (v) => h - 2 - (v / 100) * (h - 6);
      const fill = ctx.createLinearGradient(0, 0, 0, h);
      fill.addColorStop(0, "rgba(56, 189, 248, 0.55)");
      fill.addColorStop(1, "rgba(56, 189, 248, 0.02)");
      ctx.beginPath();
      ctx.moveTo(x(0), h);
      series.forEach((v, i) => ctx.lineTo(x(i), y(v)));
      ctx.lineTo(x(series.length - 1), h);
      ctx.closePath();
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.beginPath();
      series.forEach((v, i) => (i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))));
      ctx.strokeStyle = BRIGHT;
      ctx.shadowColor = CYAN;
      ctx.shadowBlur = 6;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.shadowBlur = 0;
    },
  };
}
