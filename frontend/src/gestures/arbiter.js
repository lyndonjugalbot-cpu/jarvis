// Turns per-hand observations into gesture events, one gesture at a time (spec section 7.1):
// two-hand gestures outrank one-hand ones, holds outrank swipes, and swipes wait until a pinch
// has been released for a moment.
//
// Events: cursor, charge, armed, disarmed, tap, drag_start, drag_move, drag_end,
// two_hand_start, two_hand_update, two_hand_end, maximize, restore, minimize, confirm, cancel,
// swipe {direction}.

const MIN_SPAN = 0.1; // in normalized screen units

const HOLDS = {
  fist: ["minimize", "fistHoldMs", "fistCooldownMs"],
  thumbs_up: ["confirm", "thumbHoldMs", "thumbCooldownMs"],
  thumbs_down: ["cancel", "thumbHoldMs", "thumbCooldownMs"],
};

function point(o) {
  return o.pose === "pinch" ? o.features.pinchPoint : o.features.indexTip;
}

function distance(a, b, aspect = 1) {
  const pa = a.features.pinchPoint;
  const pb = b.features.pinchPoint;
  return Math.hypot((pa.x - pb.x) * aspect, pa.y - pb.y);
}

function middle(a, b) {
  const pa = a.features.pinchPoint;
  const pb = b.features.pinchPoint;
  return { x: (pa.x + pb.x) / 2, y: (pa.y + pb.y) / 2 };
}

export function createArbiter(settings) {
  const s = settings;
  let armed = false;
  let armSince = null;
  let lastHandAt = -Infinity;
  let mode = "idle"; // idle | pending | drag | two_hand | wait_release
  let pinch = null; // { key, since }
  let two = null; // { keys, d0, ratio }
  let lastReleaseAt = -Infinity;
  let charging = false;
  const firedHold = new Map(); // hand key -> poseSince of the hold that already fired
  const cooldownUntil = {};

  function update(t, obs, aspect = 1) {
    const events = [];
    const emit = (type, data = {}) => events.push({ type, t, ...data });
    const ready = (name) => t >= (cooldownUntil[name] ?? -Infinity);
    const cool = (name, ms) => {
      cooldownUntil[name] = t + ms;
    };
    const charge = (gesture, progress, at) => {
      charging = progress > 0;
      emit("charge", { gesture, progress, ...(at ?? {}) });
    };
    const stopCharge = () => {
      if (charging) charge(null, 0);
    };
    const release = () => {
      mode = "idle";
      pinch = null;
      lastReleaseAt = t;
    };
    const startTwo = (a, b) => {
      mode = "two_hand";
      pinch = null;
      // A floor on the starting distance keeps the ratio sane when the hands start close together.
      two = { keys: [a.key, b.key], d0: Math.max(distance(a, b, aspect), MIN_SPAN), ratio: 1 };
      emit("two_hand_start", middle(a, b));
    };

    if (obs.length) {
      lastHandAt = t;
    } else if (armed && t - lastHandAt > s.autoDisarmMs) {
      armed = false;
      armSince = null;
      if (mode === "drag") emit("drag_end", {});
      mode = "idle";
      pinch = null;
      two = null;
      emit("disarmed", { reason: "no hand" });
    }

    // Cursor: the pinching hand while a pinch is in play, else a pointing hand, else the right hand.
    const primary =
      (pinch && obs.find((o) => o.key === pinch.key)) ||
      obs.find((o) => o.pose === "point") ||
      obs.find((o) => o.hand === "Right") ||
      obs[0];
    if (primary) {
      emit("cursor", { ...point(primary), armed, strength: primary.strength, hand: primary.key });
    }

    if (!armed) {
      const palm = obs.find((o) => o.pose === "open_palm" && o.speed < s.armStillSpeed);
      if (!palm) {
        armSince = null;
        stopCharge();
        return events;
      }
      armSince ??= t;
      const progress = (t - armSince) / s.armHoldMs;
      if (progress >= 1) {
        armed = true;
        armSince = null;
        stopCharge();
        emit("armed");
      } else {
        charge("arm", progress, point(palm));
      }
      return events;
    }

    // Pinches: tap, drag, and the two-hand spread/squeeze.
    const pinching = obs.filter((o) => o.pose === "pinch");
    const find = (key) => pinching.find((o) => o.key === key);
    if (mode === "idle") {
      if (pinching.length >= 2) startTwo(pinching[0], pinching[1]);
      else if (pinching.length === 1) {
        mode = "pending";
        pinch = { key: pinching[0].key, since: t };
      }
    } else if (mode === "pending") {
      const own = find(pinch.key);
      const other = pinching.find((o) => o.key !== pinch.key);
      if (!own) {
        if (t - pinch.since < s.tapMaxMs && ready("tap")) {
          const hand = obs.find((o) => o.key === pinch.key);
          emit("tap", hand ? point(hand) : {});
          cool("tap", s.tapCooldownMs);
        }
        release();
      } else if (other && t - pinch.since <= s.secondHandWaitMs) {
        startTwo(own, other);
      } else if (t - pinch.since >= s.dragHoldMs) {
        mode = "drag";
        emit("drag_start", point(own));
      }
    } else if (mode === "drag") {
      const own = find(pinch.key);
      const other = pinching.find((o) => o.key !== pinch.key);
      if (!own) {
        emit("drag_end", {});
        release();
      } else if (other) {
        emit("drag_end", { handover: true });
        startTwo(own, other);
      } else if (own.rawPose === "pinch") {
        emit("drag_move", point(own)); // skip frames where the fingers are already opening
      }
    } else if (mode === "two_hand") {
      const a = find(two.keys[0]);
      const b = find(two.keys[1]);
      if (a && b) {
        if (a.rawPose === "pinch" && b.rawPose === "pinch") {
          two.ratio = distance(a, b, aspect) / two.d0;
          emit("two_hand_update", { ratio: two.ratio, ...middle(a, b) });
        }
      } else {
        if (two.ratio >= s.spreadRatio) emit("maximize");
        else if (two.ratio <= s.squeezeRatio) emit("restore");
        emit("two_hand_end", { ratio: two.ratio });
        two = null;
        lastReleaseAt = t;
        mode = pinching.length ? "wait_release" : "idle";
      }
    } else if (mode === "wait_release" && !pinching.length) {
      mode = "idle";
    }
    if (mode !== "idle") {
      stopCharge();
      return events;
    }

    // Holds: fist, thumbs up, thumbs down. The longest-held one wins; each hold fires once.
    const holders = obs.filter((o) => HOLDS[o.pose]);
    if (holders.length) {
      const o = holders.reduce((a, b) => (a.poseSince <= b.poseSince ? a : b));
      const [event, holdKey, coolKey] = HOLDS[o.pose];
      if (firedHold.get(o.key) !== o.poseSince) {
        const progress = (t - o.poseSince) / s[holdKey];
        if (progress >= 1) {
          firedHold.set(o.key, o.poseSince);
          stopCharge();
          if (ready(event)) {
            emit(event, { hand: o.key });
            cool(event, s[coolKey]);
          }
        } else {
          charge(o.pose, progress, point(o));
        }
      }
      return events;
    }
    stopCharge();

    // Swipes with an open palm.
    if (t - lastReleaseAt < s.swipeAfterReleaseMs) return events;
    for (const o of obs) {
      if (o.pose !== "open_palm") continue;
      const { x: vx, y: vy } = o.velocity;
      if (Math.abs(vx) >= s.swipeSpeed && Math.abs(vx) >= s.swipeDominance * Math.abs(vy)) {
        if (ready("swipe")) {
          emit("swipe", { direction: vx > 0 ? "right" : "left" });
          cool("swipe", s.swipeSideCooldownMs);
        }
        break;
      }
      if (vy >= s.swipeSpeed && vy >= s.swipeDominance * Math.abs(vx)) {
        if (ready("swipe")) {
          emit("swipe", { direction: "down" });
          cool("swipe", s.swipeDownCooldownMs);
        }
        break;
      }
    }
    return events;
  }

  return {
    update,
    get armed() {
      return armed;
    },
    get mode() {
      return mode;
    },
  };
}
