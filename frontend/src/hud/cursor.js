// The fingertip cursor: a glowing dot that fills with pinch strength, and a ring that charges
// while a hold gesture builds (so you see it coming).

const HIDE_AFTER_MS = 400;
const RING = 2 * Math.PI * 22;

export function createCursor(el) {
  const charge = el.querySelector(".cursor-charge");
  charge.style.strokeDasharray = `${RING}`;
  let hideTimer = null;
  let position = null;

  return {
    get position() {
      return position;
    },
    move(sx, sy, { armed, strength = 0 }) {
      position = { x: sx, y: sy };
      el.hidden = false;
      el.style.transform = `translate(${sx * window.innerWidth}px, ${sy * window.innerHeight}px)`;
      el.classList.toggle("armed", Boolean(armed));
      el.style.setProperty("--strength", strength.toFixed(2));
      clearTimeout(hideTimer);
      hideTimer = setTimeout(() => {
        el.hidden = true;
        position = null;
      }, HIDE_AFTER_MS);
    },
    charge(progress) {
      charge.style.strokeDashoffset = `${RING * (1 - Math.max(0, Math.min(1, progress)))}`;
    },
  };
}
