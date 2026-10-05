// The confirmation prompt for risky actions. Approve with a thumbs up, a click or Y; cancel with
// a thumbs down, a click or N. The core counts 30 s of silence as no and tells every HUD.

const TIMEOUT_MS = 30000;

export function createConfirm(el, { onAnswer }) {
  const summary = el.querySelector(".confirm-summary");
  const bar = el.querySelector(".confirm-timer span");
  let pending = null;

  function hide() {
    pending = null;
    el.hidden = true;
  }

  function answer(approved) {
    if (!pending) return false;
    onAnswer(pending, approved);
    hide();
    return true;
  }

  el.querySelector(".approve").addEventListener("click", () => answer(true));
  el.querySelector(".cancel").addEventListener("click", () => answer(false));

  return {
    get pending() {
      return pending;
    },
    show({ actionId, summary: text }) {
      pending = actionId;
      summary.textContent = text;
      el.hidden = false;
      bar.style.transition = "none";
      bar.style.width = "100%";
      requestAnimationFrame(() => {
        bar.style.transition = `width ${TIMEOUT_MS}ms linear`;
        bar.style.width = "0%";
      });
    },
    done(actionId) {
      if (pending === actionId) hide();
    },
    answer,
  };
}
