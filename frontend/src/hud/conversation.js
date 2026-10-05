// The conversation panel (HUD.png): the recent exchange with JARVIS, a status line for the current
// turn with chips for the provider and the tools it used, and the text box for typing.

const KEEP_MESSAGES = 40;
const SVG = "http://www.w3.org/2000/svg";
const ICONS = {
  user: ["M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z", "M4.5 20.5a7.5 7.5 0 0 1 15 0"],
  jarvis: ["M12 21.5a9.5 9.5 0 1 0 0-19 9.5 9.5 0 0 0 0 19Z", "M12 16.5a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9Z", "M12 13.2a1.2 1.2 0 1 0 0-2.4 1.2 1.2 0 0 0 0 2.4Z"],
};
const STATUS = {
  idle: "Ready",
  listening: "Listening",
  thinking: "Processing request",
  speaking: "Speaking",
};

function icon(role) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  for (const d of ICONS[role === "user" ? "user" : "jarvis"]) {
    const path = document.createElementNS(SVG, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

function span(text) {
  const el = document.createElement("span");
  el.textContent = text;
  return el;
}

export function createConversation({ messages, tags, status, chips, form, onSubmit }) {
  const input = form.querySelector("input");
  let finished = false; // the last turn finished (so "idle" reads "Completed")

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
    // role: user | jarvis | error; meta: { provider, tools, seconds, cost }
    add(role, text, meta = {}) {
      const article = document.createElement("article");
      article.className = `msg ${role}`;
      const avatar = document.createElement("span");
      avatar.className = "avatar";
      avatar.append(icon(role));
      const body = document.createElement("div");
      const header = document.createElement("header");
      const time = document.createElement("time");
      const now = new Date();
      time.dateTime = now.toISOString();
      time.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      header.append(span(role === "user" ? "YOU" : "JARVIS"), time);
      const p = document.createElement("p");
      p.textContent = text;
      body.append(header, p);
      article.append(avatar, body);
      messages.append(article);
      while (messages.children.length > KEEP_MESSAGES) messages.firstElementChild.remove();
      messages.scrollTop = messages.scrollHeight;

      if (role === "user") {
        chips.replaceChildren();
        finished = false;
      } else if (meta.provider) {
        const items = [`${meta.provider} | ${meta.seconds ?? 0}s`, ...(meta.tools ?? [])];
        if (meta.cost) items.push(`$${meta.cost.toFixed(4)}`);
        chips.replaceChildren(...items.map(span));
        tags.textContent = [meta.provider, meta.tools?.at(-1)].filter(Boolean).join(" | ");
        finished = true;
        status.textContent = "Completed";
      }
    },
    setState(state) {
      status.textContent = state === "idle" && finished ? "Completed" : (STATUS[state] ?? STATUS.idle);
    },
    focus() {
      input.focus();
    },
  };
}
