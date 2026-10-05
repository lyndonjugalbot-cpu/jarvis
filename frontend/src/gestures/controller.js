// Maps gesture events to HUD actions: the cursor, panel hit-testing (the scene's raycaster),
// dragging, resizing, the dock. Hand coordinates come from the camera; only the central
// `activeArea` of the view maps to the screen, so the edges are reachable without stretching.

export function createController({ panels, cursor, settings, say, setIndicator }) {
  let last = null;
  let grabbed = null;
  let resizing = null;
  let handedOver = null;

  function toScreen({ x, y }) {
    const margin = (1 - settings.activeArea) / 2;
    const clamp = (v) => Math.max(0, Math.min(1, v));
    return { x: clamp((x - margin) / settings.activeArea), y: clamp((y - margin) / settings.activeArea) };
  }

  function dockItemAt(p) {
    const el = document.elementFromPoint(p.x * window.innerWidth, p.y * window.innerHeight);
    return el?.closest?.("[data-panel]") ?? null;
  }

  const on = {
    cursor(e) {
      last = toScreen(e);
      cursor.move(last.x, last.y, e);
      if (e.armed && !grabbed) panels.hover(panels.hit(last.x, last.y));
    },
    charge(e) {
      cursor.charge(e.progress);
    },
    armed() {
      setIndicator("gestures", "armed");
      say("Gestures armed.");
    },
    disarmed() {
      setIndicator("gestures", "idle", "disarmed");
      panels.hover(null);
      say("Gestures disarmed after a few seconds without a hand.");
    },
    tap() {
      if (!last) return;
      const item = dockItemAt(last);
      if (item) {
        item.click();
        return;
      }
      const panel = panels.hit(last.x, last.y);
      if (panel) {
        panels.focus(panel);
        say(`Selected ${panel.title}.`);
      }
    },
    drag_start() {
      if (!last) return;
      grabbed = panels.hit(last.x, last.y);
      if (grabbed) panels.grab(grabbed, last.x, last.y);
    },
    drag_move(e) {
      if (!grabbed) return;
      const p = toScreen(e);
      panels.dragTo(grabbed, p.x, p.y);
    },
    drag_end(e) {
      if (!grabbed) return;
      panels.release(grabbed);
      if (e.handover) handedOver = grabbed;
      grabbed = null;
    },
    two_hand_start(e) {
      const c = toScreen(e);
      resizing = handedOver ?? panels.hit(c.x, c.y) ?? panels.focused;
      handedOver = null;
    },
    two_hand_update(e) {
      if (resizing) resizing.previewScale = Math.max(0.6, Math.min(1.5, e.ratio));
    },
    maximize() {
      if (!resizing) return;
      panels.maximize(resizing);
      say(`Maximized ${resizing.title}.`);
    },
    restore() {
      if (!resizing) return;
      panels.restore(resizing);
      say(`Restored ${resizing.title}.`);
    },
    two_hand_end() {
      if (resizing) resizing.previewScale = 1;
      resizing = null;
    },
    minimize() {
      const panel = panels.focused;
      if (!panel) return;
      panels.minimize(panel);
      say(`Minimized ${panel.title}.`);
    },
    swipe(e) {
      if (e.direction === "down") {
        const panel = panels.focused;
        if (!panel) return;
        panels.close(panel);
        say(`Closed ${panel.title}.`);
        return;
      }
      const panel = panels.cycleFocus(e.direction === "right" ? 1 : -1);
      if (panel) say(`Focused ${panel.title}.`);
    },
    // Phase 3 sends these to the core to answer a confirm_request.
    confirm() {
      say("Thumbs up: nothing is waiting for confirmation yet.");
    },
    cancel() {
      say("Thumbs down: nothing to cancel.");
    },
  };

  return {
    handle(events) {
      for (const e of events) on[e.type]?.(e);
    },
  };
}
