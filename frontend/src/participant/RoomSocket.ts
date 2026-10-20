import { useCallback, useEffect, useRef, useState } from "react";

import type { ServerMessage } from "../shared/types";
import type { ClientMessage } from "./apiTypes";
import { formatSocketUrl } from "./time";

export type SocketStatus = "connecting" | "open" | "closed";

interface UseRoomSocketResult {
  status: SocketStatus;
  send: (message: ClientMessage) => boolean;
  superseded: boolean;
}

const RECONNECT_DELAY_MS = 1500;
const HEARTBEAT_INTERVAL_MS = 20000;

export function useRoomSocket(
  roomId: string,
  active: boolean,
  onMessage: (message: ServerMessage) => void,
): UseRoomSocketResult {
  const [status, setStatus] = useState<SocketStatus>("connecting");
  const [superseded, setSuperseded] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const heartbeatTimerRef = useRef<number | null>(null);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  const send = useCallback((message: ClientMessage): boolean => {
    const socket = socketRef.current;
    if (socket === null || socket.readyState !== WebSocket.OPEN) {
      return false;
    }
    socket.send(JSON.stringify(message));
    return true;
  }, []);

  useEffect(() => {
    if (!active) {
      return;
    }
    setSuperseded(false);
    let disposed = false;

    const clearReconnect = () => {
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };

    const connect = () => {
      if (disposed) return;
      clearReconnect();
      setStatus("connecting");
      const socket = new WebSocket(formatSocketUrl());
      socketRef.current = socket;

      socket.onopen = () => {
        if (disposed) {
          socket.close();
          return;
        }
        setStatus("open");
        socket.send(JSON.stringify({ type: "enter_room", roomId }));
      };

      socket.onmessage = (event: MessageEvent) => {
        if (disposed || typeof event.data !== "string") return;
        let parsed: unknown;
        try {
          parsed = JSON.parse(event.data);
        } catch {
          return;
        }
        if (parsed === null || typeof parsed !== "object") return;
        if (typeof (parsed as { type?: unknown }).type !== "string") return;
        onMessageRef.current(parsed as ServerMessage);
      };

      socket.onclose = (event) => {
        if (socketRef.current === socket) {
          socketRef.current = null;
        }
        if (disposed) return;
        setStatus("closed");
        clearReconnect();
        if (event.code === 4000) {
          if (heartbeatTimerRef.current !== null) {
            window.clearInterval(heartbeatTimerRef.current);
            heartbeatTimerRef.current = null;
          }
          setSuperseded(true);
          return;
        }
        reconnectTimerRef.current = window.setTimeout(connect, RECONNECT_DELAY_MS);
      };

      socket.onerror = () => {
        // 连接失败时浏览器随后会触发 close，由 close 负责重连。
      };
    };

    connect();
    heartbeatTimerRef.current = window.setInterval(() => {
      const socket = socketRef.current;
      if (socket !== null && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "ping", roomId }));
      }
    }, HEARTBEAT_INTERVAL_MS);

    return () => {
      disposed = true;
      clearReconnect();
      if (heartbeatTimerRef.current !== null) {
        window.clearInterval(heartbeatTimerRef.current);
        heartbeatTimerRef.current = null;
      }
      const socket = socketRef.current;
      socketRef.current = null;
      if (socket !== null) {
        socket.onclose = null;
        socket.close();
      }
    };
  }, [roomId, active]);

  return { status, send, superseded };
}
