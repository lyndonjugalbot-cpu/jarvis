// Short UI sounds (spec 5.2, optional): synthesized with WebAudio, so there are no audio files.
// Browsers only allow sound after the page has had a click or key press.

const CUES = {
  open: [[660, 70], [990, 90]],
  close: [[520, 60], [330, 110]],
  grab: [[880, 45]],
  armed: [[440, 60], [660, 60], [880, 90]],
  alert: [[740, 120], [740, 120]],
};

export function createSounds({ enabled = true } = {}) {
  let ctx = null;
  const state = { enabled };

  function tone(freq, ms, at) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, at);
    gain.gain.exponentialRampToValueAtTime(0.06, at + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, at + ms / 1000);
    osc.connect(gain).connect(ctx.destination);
    osc.start(at);
    osc.stop(at + ms / 1000 + 0.02);
  }

  return {
    get enabled() {
      return state.enabled;
    },
    set enabled(value) {
      state.enabled = value;
    },
    play(cue) {
      if (!state.enabled || !CUES[cue]) return;
      try {
        ctx ??= new AudioContext();
        let at = ctx.currentTime;
        for (const [freq, ms] of CUES[cue]) {
          tone(freq, ms, at);
          at += ms / 1000 + 0.02;
        }
      } catch {
        // no audio device, or the browser hasn't allowed sound yet
      }
    },
  };
}
