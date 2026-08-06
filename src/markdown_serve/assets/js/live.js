import { status, finder } from "./dom.js";
import { state } from "./state.js";
import { renderNav } from "./nav.js";
import { load } from "./content.js";

const MAX_RECONNECT_ATTEMPTS = 3;
let reconnectAttempts = 0;
let reconnectTimer = null;
let activeSocket = null;

function clearReconnectTimer() {
  if (reconnectTimer != null) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
}

function showDisconnected() {
  clearReconnectTimer();
  status.classList.remove("live");
  status.classList.add("offline");
  status.replaceChildren();
  status.append("disconnected");
  const btn = document.createElement("button");
  btn.type = "button";
  btn.id = "reconnect-btn";
  btn.className = "reconnect-btn";
  btn.textContent = "Reconnect";
  btn.addEventListener("click", () => {
    reconnectAttempts = 0;
    connect();
  });
  status.appendChild(btn);
}

export function connect() {
  clearReconnectTimer();
  if (activeSocket) {
    activeSocket.onopen = null;
    activeSocket.onclose = null;
    activeSocket.onmessage = null;
    activeSocket.onerror = null;
    try { activeSocket.close(); } catch (_) {}
    activeSocket = null;
  }

  status.classList.remove("live", "offline");
  status.textContent = reconnectAttempts > 0
    ? `reconnecting (${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})…`
    : "connecting…";

  const proto = location.protocol === "https:" ? "wss" : "ws";
  let ws;
  try {
    ws = new WebSocket(proto + "://" + location.host + "/__ws");
  } catch (_) {
    reconnectAttempts += 1;
    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      showDisconnected();
      return;
    }
    reconnectTimer = setTimeout(connect, 800);
    return;
  }
  activeSocket = ws;

  ws.onopen = () => {
    reconnectAttempts = 0;
    status.classList.remove("offline");
    status.classList.add("live");
    status.textContent = "live";
  };

  ws.onclose = () => {
    if (activeSocket === ws) activeSocket = null;
    status.classList.remove("live");
    reconnectAttempts += 1;
    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      showDisconnected();
      return;
    }
    status.classList.remove("offline");
    status.textContent = `reconnecting (${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})…`;
    reconnectTimer = setTimeout(connect, 800);
  };

  ws.onmessage = async (ev) => {
    const changed = ev.data;
    try {
      const res = await fetch("/__api/files");
      const files = await res.json();
      renderNav(files, state.currentPath, finder.value);
      if (!state.currentPath && files.length) state.currentPath = files[0];
      if (state.currentPath && files.includes(state.currentPath)) await load(state.currentPath);
      else if (files.includes(changed)) await load(changed);
    } catch (_) {
      if (state.currentPath) await load(state.currentPath);
    }
  };
}
