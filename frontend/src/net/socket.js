// WebSocket link to the core (spec section 8): the token goes in the first message, the link
// reconnects on its own with backoff, and messages are routed by type.
// Messages are JSON: { type, payload, id }.

const FIRST_RETRY_MS = 500;
const MAX_RETRY_MS = 5000;

export function createSocket({ url, token, onStatus = () => {} }) {
  const handlers = new Map();
  let ws = null;
  let authed = false;
  let retryMs = FIRST_RETRY_MS;
  let nextId = 0;

  function connect() {
    onStatus("connecting");
    ws = new WebSocket(url);
    ws.addEventListener("open", () => {
      ws.send(JSON.stringify({ type: "auth", payload: { token }, id: `h${++nextId}` }));
    });
    ws.addEventListener("message", (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      if (message.type === "auth_ok") {
        authed = true;
        retryMs = FIRST_RETRY_MS;
        onStatus("online");
      }
      for (const handler of handlers.get(message.type) ?? []) handler(message.payload ?? {}, message);
    });
    ws.addEventListener("close", (event) => {
      authed = false;
      onStatus(event.code === 4401 ? "unauthorized" : event.code === 4403 ? "forbidden" : "offline");
      setTimeout(connect, retryMs);
      retryMs = Math.min(retryMs * 2, MAX_RETRY_MS);
    });
  }

  connect();
  return {
    on(type, handler) {
      if (!handlers.has(type)) handlers.set(type, []);
      handlers.get(type).push(handler);
    },
    // Handle a message as if the core had sent it (dev hooks and demos).
    emit(type, payload = {}) {
      for (const handler of handlers.get(type) ?? []) handler(payload, { type, payload });
    },
    send(type, payload = {}) {
      if (!authed || ws?.readyState !== WebSocket.OPEN) return false;
      ws.send(JSON.stringify({ type, payload, id: `h${++nextId}` }));
      return true;
    },
    get online() {
      return authed;
    },
  };
}
