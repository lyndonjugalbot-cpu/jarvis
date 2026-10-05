// Keeps the panels: focus, hover, dragging, maximize/minimize/close and the dock.

import { Panel } from "./panel.js";

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
  constructor(view, dockEl) {
    this.view = view;
    this.dock = createDock(dockEl);
    this.panels = [];
    this.focused = null;
    this.grabOffset = null;
  }

  layout() {
    const fit = this.view.viewSize(1.5);
    const maxScale = (p) => Math.min((0.82 * fit.width) / p.size.w, (0.72 * fit.height) / p.size.h);
    return { dock: this.view.pointAt(0.06, 0.96, 0), maxScale };
  }

  setState(panel, state) {
    const { dock, maxScale } = this.layout();
    panel.setState(state, { dock, maxScale: maxScale(panel) });
    this.refreshFocusMode();
  }

  // Focus mode: while a panel is maximized the others (and the orb) fade back.
  refreshFocusMode() {
    const big = this.panels.find((p) => p.state === "maximized" && !p.closing);
    for (const p of this.panels) p.setDimmed(Boolean(big) && p !== big);
    document.body.classList.toggle("panel-maximized", Boolean(big));
  }

  add(spec) {
    const panel = new Panel(spec);
    this.view.scene.add(panel.mesh);
    this.view.cssScene.add(panel.cssObject);
    this.panels.push(panel);
    this.focus(panel);
    return panel;
  }

  find(id) {
    return this.panels.find((p) => p.id === id) ?? null;
  }

  visible() {
    return this.panels.filter((p) => p.state !== "minimized" && !p.closing);
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

  release(panel) {
    panel?.setLook({ grabbed: false });
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

  minimize(panel) {
    if (!panel || panel.state === "minimized") return;
    this.setState(panel, "minimized");
    this.dock.add(panel, () => this.unminimize(panel));
    if (this.focused === panel) this.focused = null;
    this.cycleFocus(1);
  }

  unminimize(panel) {
    this.dock.remove(panel);
    this.setState(panel, "focused");
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
    this.refreshFocusMode();
    this.cycleFocus(1);
  }

  update(dt, cursor) {
    for (const p of [...this.panels]) p.update(dt, cursor);
  }
}
