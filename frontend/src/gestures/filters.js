// One Euro filter (Casiez, Roussel & Vogel, 2012): heavy smoothing while the hand is still,
// light smoothing while it moves, so the cursor is steady without lagging.

function alpha(cutoffHz, dtS) {
  const tau = 1 / (2 * Math.PI * cutoffHz);
  return 1 / (1 + tau / dtS);
}

export class OneEuroFilter {
  constructor({ minCutoff = 1.5, beta = 8, dCutoff = 1 } = {}) {
    this.minCutoff = minCutoff;
    this.beta = beta;
    this.dCutoff = dCutoff;
    this.value = null;
    this.speed = 0;
    this.t = 0;
  }

  filter(x, tMs) {
    if (this.value === null) {
      this.value = x;
      this.t = tMs;
      return x;
    }
    const dt = Math.max((tMs - this.t) / 1000, 1e-3);
    this.speed += alpha(this.dCutoff, dt) * ((x - this.value) / dt - this.speed);
    const cutoff = this.minCutoff + this.beta * Math.abs(this.speed);
    this.value += alpha(cutoff, dt) * (x - this.value);
    this.t = tMs;
    return this.value;
  }
}

// Smooths the 21 landmarks of one hand.
export class LandmarkSmoother {
  constructor(options) {
    this.options = options;
    this.filters = null;
  }

  smooth(landmarks, tMs) {
    this.filters ??= landmarks.map(() => [0, 1, 2].map(() => new OneEuroFilter(this.options)));
    return landmarks.map((p, i) => {
      const [fx, fy, fz] = this.filters[i];
      return { x: fx.filter(p.x, tMs), y: fy.filter(p.y, tMs), z: fz.filter(p.z ?? 0, tMs) };
    });
  }
}
