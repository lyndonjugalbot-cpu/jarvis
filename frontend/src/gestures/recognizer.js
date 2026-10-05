// Follows each hand over time: a pose only counts once it has held for `stableFrames` frames,
// `poseSince` says when the current pose began (hold timers restart when the shape changes),
// and wrist velocity is measured in hand sizes per second.

import { classify, measure, pinchStrength, trueHandedness } from "./pose.js";

export function createRecognizer(settings) {
  const hands = new Map();

  function view(st) {
    return {
      key: st.key,
      hand: st.hand,
      pose: st.pose,
      rawPose: st.rawPose,
      poseSince: st.poseSince,
      features: st.features,
      velocity: st.velocity,
      speed: Math.hypot(st.velocity.x, st.velocity.y),
      strength: pinchStrength(st.features, settings),
    };
  }

  function update(frame) {
    const s = settings;
    const seen = new Set();
    const out = [];

    for (const raw of frame.hands) {
      if ((raw.score ?? 1) < s.minConfidence) continue;
      const hand = trueHandedness(raw.handedness, s);
      const key = seen.has(hand) ? `${hand}#2` : hand;
      seen.add(key);

      const features = measure(raw.landmarks, frame.aspect, hand, s);
      const st = hands.get(key) ?? {
        key,
        hand,
        pose: "none",
        poseSince: frame.t,
        candidate: null,
        candidateSince: frame.t,
        count: 0,
        rawPose: "none",
        history: [],
        velocity: { x: 0, y: 0 },
      };
      const rawPose = classify(features, s, st.rawPose === "pinch");
      if (rawPose === st.candidate) {
        st.count += 1;
      } else {
        st.candidate = rawPose;
        st.candidateSince = frame.t;
        st.count = 1;
      }
      if (st.count >= s.stableFrames && st.pose !== st.candidate) {
        st.pose = st.candidate;
        st.poseSince = st.candidateSince;
      }
      st.rawPose = rawPose;

      st.history.push({ t: frame.t, x: features.wrist.x * frame.aspect, y: features.wrist.y });
      while (st.history.length > 2 && frame.t - st.history[0].t > s.velocityWindowMs) st.history.shift();
      const first = st.history[0];
      const dt = (frame.t - first.t) / 1000;
      const last = st.history[st.history.length - 1];
      st.velocity =
        dt > 0
          ? { x: (last.x - first.x) / dt / features.size, y: (last.y - first.y) / dt / features.size }
          : { x: 0, y: 0 };

      st.features = features;
      st.lastSeen = frame.t;
      hands.set(key, st);
      out.push(view(st));
    }

    for (const [key, st] of hands) {
      if (seen.has(key)) continue;
      if (frame.t - st.lastSeen <= s.lostGraceMs) out.push(view(st));
      else hands.delete(key);
    }
    return out;
  }

  return { update };
}
