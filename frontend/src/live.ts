import type { Connection, LiveEvent } from "./types";

export function connectLive(
  onEvent: (event: LiveEvent) => void,
  onStatus: (status: Connection) => void,
): () => void {
  let stopped = false;
  let socket: WebSocket | undefined;
  let reconnect: ReturnType<typeof setTimeout> | undefined;
  let watchdog: ReturnType<typeof setInterval> | undefined;
  let failures = 0;
  let lastReceived = Date.now();
  const open = () => {
    if (stopped) return;
    onStatus("connecting");
    socket = new WebSocket(
      `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/live`,
    );
    socket.onopen = () => {
      lastReceived = Date.now();
      watchdog = setInterval(() => {
        if (Date.now() - lastReceived > 65000) socket?.close();
      }, 10000);
    };
    socket.onmessage = ({ data }) => {
      lastReceived = Date.now();
      try {
        const event = JSON.parse(data) as LiveEvent;
        if (event.type === "ping") {
          socket?.send(JSON.stringify({ type: "pong" }));
          return;
        }
        failures = 0;
        onStatus("online");
        onEvent(event);
      } catch {
        socket?.close();
      }
    };
    socket.onclose = ({ code }) => {
      if (watchdog) clearInterval(watchdog);
      if (stopped) return;
      if (code === 4401 || code === 4403) {
        onStatus("unauthorized");
        return;
      }
      onStatus("offline");
      reconnect = setTimeout(
        open,
        Math.min(15000, 1000 * 2 ** Math.min(failures++, 4)),
      );
    };
    socket.onerror = () => socket?.close();
  };
  open();
  return () => {
    stopped = true;
    if (reconnect) clearTimeout(reconnect);
    if (watchdog) clearInterval(watchdog);
    socket?.close();
  };
}
