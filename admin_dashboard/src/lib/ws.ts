import { WS_URL } from "./api";
import type { Message } from "./api";

export type WsHandler = (message: Message) => void;

export function connectAdminWs(onMessage: WsHandler): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  let retryMs = 1000;

  const connect = () => {
    if (closed) return;
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      retryMs = 1000;
      ws?.send("ping");
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data as string) as {
          type?: string;
          message?: Message;
        };
        if (data.type === "message.new" && data.message) {
          onMessage(data.message);
        }
      } catch {
        /* ignore */
      }
    };

    ws.onclose = () => {
      if (closed) return;
      setTimeout(connect, retryMs);
      retryMs = Math.min(retryMs * 2, 15000);
    };

    ws.onerror = () => {
      ws?.close();
    };
  };

  connect();

  const ping = setInterval(() => {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send("ping");
    }
  }, 25000);

  return () => {
    closed = true;
    clearInterval(ping);
    ws?.close();
  };
}
