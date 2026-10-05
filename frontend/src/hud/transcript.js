// The transcript strip: the last few lines of the conversation, a one-line status for HUD
// feedback (gestures, camera), and the text box for typing to JARVIS.

const KEEP_LINES = 3;

export function createTranscript(el, { onSubmit }) {
  const lines = el.querySelector(".lines");
  const status = el.querySelector(".status");
  const form = el.querySelector("form");
  const input = form.querySelector("input");

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    if (onSubmit(text)) input.value = "";
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") input.blur();
  });

  return {
    add(role, text, meta = "") {
      const line = document.createElement("p");
      line.className = `line ${role}`;
      const who = document.createElement("span");
      who.className = "who";
      who.textContent = role === "user" ? "You" : role === "error" ? "!" : "JARVIS";
      const body = document.createElement("span");
      body.textContent = text;
      line.append(who, body);
      if (meta) {
        const small = document.createElement("small");
        small.textContent = meta;
        line.append(small);
      }
      lines.append(line);
      while (lines.children.length > KEEP_LINES) lines.firstElementChild.remove();
    },
    status(text) {
      status.textContent = text;
    },
    focus() {
      input.focus();
    },
  };
}
