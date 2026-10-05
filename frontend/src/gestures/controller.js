// Maps gesture events to HUD actions: the cursor, panel hit-testing (the scene's raycaster),
// dragging, resizing, the dock, and the holographic model on the stage. Hand coordinates come
// from the camera; only the central `activeArea` of the view maps to the screen, so the edges are
// reachable without stretching.
//
// Panels come first. Over the stage, while a model is showing: pinch-drag turns it, two pinched
// hands spread apart break it into its parts (squeeze to put it back), a pinch selects a part, a
// fist puts it back together (or, when it's together, puts it away), and a sideways swipe shows
// the next model.

import { spreadToExplode } from "../hud/holograms/explode.js";

export function createController({ panels, model = null, cursor, settings, say, setIndicator, onConfirm }) {
  let last = null;
  let grabbed = null;
  let resizing = null;
  let handedOver = null;
  let turning = false;
  let exploding = null; // { base } while two hands pull the model apart

  const overModel = (p = last) => Boolean(model?.active && p && model.contains(p.x, p.y));

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
      if (e.armed && !grabbed && !turning) {
        const panel = panels.hit(last.x, last.y);
        panels.hover(panel);
        model?.hover(!panel && overModel() ? model.hit(last.x, last.y) : null);
      }
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
      model?.hover(null);
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
      } else if (overModel()) {
        const part = model.select(model.hit(last.x, last.y));
        say(part ? `${part.name}.` : `Showing all of the ${model.title.toLowerCase()}.`);
      }
    },
    drag_start() {
      if (!last) return;
      grabbed = panels.hit(last.x, last.y);
      if (grabbed) panels.grab(grabbed, last.x, last.y);
      else if (overModel()) {
        turning = true;
        model.beginTurn(last.x, last.y);
      }
    },
    drag_move(e) {
      const p = toScreen(e);
      if (turning) model.turnTo(p.x, p.y);
      if (!grabbed) return;
      panels.dragTo(grabbed, p.x, p.y);
    },
    drag_end(e) {
      if (turning) {
        model.endTurn();
        turning = false;
      }
      if (!grabbed) return;
      panels.release(grabbed);
      if (e.handover) handedOver = grabbed;
      grabbed = null;
    },
    two_hand_start(e) {
      const c = toScreen(e);
      const panel = handedOver ?? panels.hit(c.x, c.y);
      handedOver = null;
      // Two hands not on a panel work the model, wherever they are.
      if (!panel && model?.active) {
        exploding = { base: model.explode };
        resizing = null;
        return;
      }
      resizing = panel ?? panels.focused;
    },
    two_hand_update(e) {
      if (exploding) {
        model.setExplode(spreadToExplode(exploding.base, e.ratio));
        return;
      }
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
      if (exploding) {
        const apart = model.explode;
        if (Math.abs(apart - exploding.base) > 0.05) say(apart > 0.5 ? `${model.title}, broken apart.` : `${model.title}, put back together.`);
        exploding = null;
      }
      if (resizing) resizing.previewScale = 1;
      resizing = null;
    },
    minimize() {
      if (overModel()) {
        if (model.explode > 0.05) {
          model.setExplode(0);
          say(`${model.title}, put back together.`);
        } else {
          say(`Put the ${model.title.toLowerCase()} away.`);
          model.close();
        }
        return;
      }
      const panel = panels.focused;
      if (!panel) return;
      panels.minimize(panel);
      say(`Minimized ${panel.title}.`);
    },
    swipe(e) {
      if (overModel()) {
        if (e.direction === "down") {
          say(`Put the ${model.title.toLowerCase()} away.`);
          model.close();
        } else if (e.direction === "left" || e.direction === "right") {
          model
            .cycle(e.direction === "right" ? 1 : -1)
            .then((title) => title && say(`${title}.`))
            .catch((err) => say(`Couldn't show that model: ${err.message}`));
        }
        return;
      }
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
    // Thumbs up / down answer a pending confirm_request from the core.
    confirm() {
      if (!onConfirm?.(true)) say("Thumbs up: nothing is waiting for approval.");
    },
    cancel() {
      if (!onConfirm?.(false)) say("Thumbs down: nothing to cancel.");
    },
  };

  return {
    handle(events) {
      for (const e of events) on[e.type]?.(e);
    },
  };
}
