// Settings drawer (press S): every gesture threshold, tunable live and remembered in this browser.

import { SETTINGS, defaultSettings } from "../gestures/settings.js";

const STORAGE_KEY = "jarvis.gestureSettings";

export function loadSettings() {
  const settings = defaultSettings();
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
    for (const [key, value] of Object.entries(saved)) {
      if (key in settings && typeof value === typeof settings[key]) settings[key] = value;
    }
  } catch {
    // storage blocked or corrupt: use the defaults
  }
  return settings;
}

function save(settings) {
  const defaults = defaultSettings();
  const changed = Object.fromEntries(Object.entries(settings).filter(([k, v]) => v !== defaults[k]));
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(changed));
  } catch {
    // not saved; the change still applies until reload
  }
}

export function createSettingsDrawer(el, settings, onChange = () => {}) {
  const list = el.querySelector(".settings-list");

  function render() {
    list.replaceChildren();
    for (const spec of SETTINGS) {
      const row = document.createElement("label");
      row.className = "setting";
      const name = document.createElement("span");
      name.textContent = spec.label;
      row.append(name);
      const input = document.createElement("input");
      if (typeof spec.value === "boolean") {
        input.type = "checkbox";
        input.checked = settings[spec.key];
        input.addEventListener("change", () => update(spec.key, input.checked));
        row.append(input);
      } else {
        input.type = "range";
        Object.assign(input, { min: spec.min, max: spec.max, step: spec.step, value: settings[spec.key] });
        const value = document.createElement("output");
        value.textContent = settings[spec.key];
        input.addEventListener("input", () => {
          value.textContent = input.value;
          update(spec.key, Number(input.value));
        });
        row.append(input, value);
      }
      list.append(row);
    }
  }

  function update(key, value) {
    settings[key] = value;
    save(settings);
    onChange(key);
  }

  el.querySelector(".settings-reset").addEventListener("click", () => {
    Object.assign(settings, defaultSettings());
    save(settings);
    render();
    onChange(null);
  });

  render();
  return {
    toggle() {
      el.hidden = !el.hidden;
    },
  };
}
