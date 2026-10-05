// Keeps the panels: the dashboard's panel slot, focus, hover, dragging, maximize/minimize/close
// and the dock. Panels open in the slot (left column, newest on top, at most MAX_IN_SLOT there;
// the one looked at least recently moves to the dock). A panel dragged out of the slot floats
// where it is dropped; dropping it back on the slot docks it again.

import * as THREE from "three";

import { Panel } from "./panel.js";

const MAX_IN_SLOT = 2;
const GAP = 0.16; // world units between stacked panels
const MAX_Z = 0.5; // a maximized panel comes forward a little
const TOP_PX = 100; // the status bar
const BOTTOM_PX = 110; // the input bar stays usable while a panel is maximized

function createDock(el) {
  return {
    add(panel, onRestore) {
      const button = document.createElement("button");
      button.className = "dock-item";
      button.dataset.panel = panel.id;
      button.textContent = panel.title;
      button.addEventListener("click", onRestore);
      el.append(button);
    },
    remove(panel) {
      el.querySelector(`[data-panel="${panel.id}"]`)?.remove();
    },
  };
}

export class PanelManager {
  constructor(view, layout, { slot, dock }) {
    this.view = view;
    this.layout = layout;
    this.slotEl = slot;
    this.dock = createDock(dock);
    this.panels = [];
    this.focused = null;
    this.grabOffset = null;
    this.order = 0;
    window.addEventListener("resize", () => this.arrange());
    new ResizeObserver(() => this.arrange()).observe(slot);
  }

  slot() {
    return this.layout.rectOf(this.slotEl);
  }

  visible() {
    return this.panels.filter((p) => p.state !== "minimized" && !p.closing);
  }

  docked() {
    return this.visible()
      .filter((p) => p.docked)
      .sort((a, b) => b.order - a.order);
  }

  // Stack the docked panels in the slot and keep every panel's text at 1:1 with the screen.
  arrange() {
    const px = this.layout.pxPerUnit(0);
    for (const p of this.panels) {
      if (p.pxPerUnit !== px) {
        p.pxPerUnit = px;
        p.expand = 0;
      }
    }
    const s = this.slot();
    const list = this.docked();
    this.slotEl.classList.toggle("empty", !list.length);
    if (s.visible && list.length) {
      const h = (s.h - GAP * (list.length - 1)) / list.length;
      list.forEach((p, i) => {
        p.moveHome(new THREE.Vector3(s.x, s.y + s.h / 2 - h / 2 - i * (h + GAP), 0));
        if (p.state === "maximized") p.restSize = { w: s.w, h };
        else p.resize(s.w, h);
      });
    }
    for (const p of this.panels) {
      if (p.state !== "maximized" || p.closing) continue;
      const big = this.maxSize();
      p.resize(big.w, big.h);
      p.setState("maximized", this.stateLayout(p));
    }
  }

  // The size of a maximized panel: the space between the status bar and the input bar, at most
  // 1.6 times as wide as it is tall.
  maxSize() {
    const H = window.innerHeight;
    const fit = this.view.viewSize(MAX_Z);
    const h = 0.94 * ((H - TOP_PX - BOTTOM_PX) / H) * fit.height;
    return { w: Math.min(0.62 * fit.width, h * 1.6), h };
  }

  // Maximizing gives the panel the bigger shape (so more of its content fits at the same text
  // size); it starts at about its old size and grows. Leaving gives the old shape back.
  reshape(panel, state) {
    const was = { ...panel.size };
    if (state === "maximized" && panel.state !== "maximized") {
      panel.restSize = was;
      const big = this.maxSize();
      panel.resize(big.w, big.h);
    } else if (state !== "maximized" && panel.state === "maximized" && panel.restSize) {
      panel.resize(panel.restSize.w, panel.restSize.h);
      panel.restSize = null;
    } else {
      return;
    }
    const k = Math.min(was.w / panel.size.w, was.h / panel.size.h);
    panel.mesh.scale.multiplyScalar(k);
  }

  // Too many panels in the slot: the one looked at least recently (not `keep`) goes to the dock.
  makeRoom(keep) {
    const others = this.docked().filter((p) => p !== keep);
    while (others.length >= MAX_IN_SLOT) {
      const oldest = others.sort((a, b) => a.touchedAt - b.touchedAt).shift();
      this.minimize(oldest, { refocus: false });
    }
  }

  stateLayout(panel) {
    const H = window.innerHeight;
    const top = TOP_PX / H;
    const bottom = (H - BOTTOM_PX) / H;
    const big = this.maxSize();
    const maxScale = Math.min(big.w / panel.size.w, big.h / panel.size.h);
    const s = this.slot();
    return {
      dock: new THREE.Vector3(s.x - s.w / 2 + 0.4, s.y - s.h / 2, 0),
      center: this.view.pointAt(0.5, (top + bottom) / 2, MAX_Z),
      maxScale,
    };
  }

  setState(panel, state) {
    this.reshape(panel, state);
    panel.setState(state, this.stateLayout(panel));
    this.refreshFocusMode();
  }

  get maximized() {
    return this.panels.find((p) => p.state === "maximized" && !p.closing) ?? null;
  }

  // Focus mode: while a panel is maximized the others and the dashboard fade back.
  refreshFocusMode() {
    const big = this.maximized;
    for (const p of this.panels) p.setDimmed(Boolean(big) && p !== big);
    document.body.classList.toggle("panel-maximized", Boolean(big));
  }

  add(spec) {
    this.makeRoom(null);
    const panel = new Panel(spec);
    panel.order = ++this.order;
    panel.pxPerUnit = this.layout.pxPerUnit(0);
    this.view.scene.add(panel.mesh);
    this.view.cssScene.add(panel.cssObject);
    this.panels.push(panel);
    this.arrange();
    panel.mesh.position.copy(panel.home); // open in place rather than fly in
    this.focus(panel);
    return panel;
  }

  // Open a panel from the core, or update it if it is already here.
  show(spec) {
    const existing = this.find(spec.id);
    if (!existing) return this.add(spec);
    existing.setContent(spec.title ?? existing.title, spec.data ?? existing.data, spec.type ?? existing.type);
    if (existing.state === "minimized") this.unminimize(existing);
    else this.focus(existing);
    return existing;
  }

  find(id) {
    return this.panels.find((p) => p.id === id) ?? null;
  }

  hit(sx, sy) {
    const meshes = this.visible()
      .filter((p) => !p.dimmed)
      .map((p) => p.mesh);
    const [first] = this.view.ray(sx, sy).intersectObjects(meshes, false);
    return first?.object.userData.panel ?? null;
  }

  hover(panel) {
    for (const p of this.panels) p.setLook({ hovered: p === panel });
  }

  focus(panel) {
    if (!panel) return;
    panel.touchedAt = performance.now();
    for (const p of this.visible()) {
      if (p !== panel && p.state === "focused") this.setState(p, "normal");
    }
    if (panel.state === "normal" || panel.state === "minimized") this.setState(panel, "focused");
    this.focused = panel;
  }

  cycleFocus(step) {
    const list = this.visible();
    if (!list.length) return null;
    const i = list.indexOf(this.focused);
    const next = list[(i + step + list.length) % list.length];
    this.focus(next);
    return next;
  }

  grab(panel, sx, sy) {
    if (panel.state === "maximized") this.setState(panel, "focused");
    this.focus(panel);
    panel.setLook({ grabbed: true });
    const at = this.view.pointAt(sx, sy, panel.mesh.position.z);
    this.grabOffset = panel.home.clone().sub(at);
    this.grabOffset.z = 0;
  }

  dragTo(panel, sx, sy) {
    const at = this.view.pointAt(sx, sy, panel.home.z);
    panel.moveHome(at.add(this.grabOffset));
  }

  // Dropped on the slot: docked again. Anywhere else: it floats there.
  release(panel) {
    if (!panel) return;
    panel.setLook({ grabbed: false });
    const s = this.slot();
    const inSlot = Math.abs(panel.home.x - s.x) < s.w / 2 && Math.abs(panel.home.y - s.y) < s.h / 2;
    if (inSlot && !panel.docked) {
      panel.docked = true;
      panel.order = ++this.order;
      this.makeRoom(panel);
    } else if (!inSlot) {
      panel.docked = false;
    }
    this.arrange();
  }

  maximize(panel) {
    if (!panel) return;
    this.focus(panel);
    this.setState(panel, "maximized");
  }

  restore(panel) {
    if (!panel) return;
    this.setState(panel, "focused");
    this.focus(panel);
  }

  minimize(panel, { refocus = true } = {}) {
    if (!panel || panel.state === "minimized") return;
    this.setState(panel, "minimized");
    this.dock.add(panel, () => this.unminimize(panel));
    if (this.focused === panel) this.focused = null;
    this.arrange();
    if (refocus) this.cycleFocus(1);
  }

  unminimize(panel) {
    this.dock.remove(panel);
    panel.docked = true;
    panel.order = ++this.order;
    panel.touchedAt = performance.now();
    this.makeRoom(panel);
    this.setState(panel, "focused");
    this.arrange();
    this.focus(panel);
  }

  close(panel) {
    if (!panel || panel.closing) return;
    if (this.focused === panel) this.focused = null;
    panel.close(() => {
      this.panels = this.panels.filter((p) => p !== panel);
      this.view.scene.remove(panel.mesh);
      this.view.cssScene.remove(panel.cssObject);
      panel.dispose();
    });
    this.arrange();
    this.refreshFocusMode();
    this.cycleFocus(1);
  }

  update(dt, cursor) {
    for (const p of [...this.panels]) p.update(dt, cursor);
  }
}
