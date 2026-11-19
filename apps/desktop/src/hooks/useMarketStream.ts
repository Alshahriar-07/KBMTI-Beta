import { useEffect, useRef, useState } from "react";

import { WS_URL } from "@/lib/api";
import type {
  ForecastRun,
  ForecastStatus,
  Mt5Status,
  Snapshot,
  StreamEvent,
  StreamHello,
} from "@/lib/types";
import { publishLiveCandle } from "@/state/live-candles";

export type TransportState = "connecting" | "open" | "reconnecting" | "closed";

interface StreamState {
  status: Mt5Status | null;
  snapshot: Snapshot | null;
  forecast: ForecastStatus | null;
  latestForecast: ForecastRun | null;
  serverTime: string | null;
  transport: TransportState;
  lastEventAt: Date | null;
}

export function useMarketStream(enabled = true): StreamState {
  const [state, setState] = useState<StreamState>({
    status: null,
    snapshot: null,
    forecast: null,
    latestForecast: null,
    serverTime: null,
    transport: "connecting",
    lastEventAt: null,
  });
  const socketRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled) {
      setState((previous) => ({ ...previous, transport: "closed" }));
      return;
    }

    let disposed = false;

    const clearTimer = () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };

    const connect = () => {
      if (disposed) return;
      setState((previous) => ({
        ...previous,
        transport: retryRef.current === 0 ? "connecting" : "reconnecting",
      }));

      let socket: WebSocket;
      try {
        socket = new WebSocket(WS_URL);
      } catch {
        scheduleReconnect();
        return;
      }
      socketRef.current = socket;

      socket.onopen = () => {
        if (disposed) return;
        retryRef.current = 0;
        setState((previous) => ({ ...previous, transport: "open" }));
      };

      socket.onmessage = (message) => {
        if (disposed) return;
        let event: StreamEvent;
        try {
          event = JSON.parse(String(message.data)) as StreamEvent;
        } catch {
          return;
        }
        const receivedAt = new Date();
        if (event.type === "hello") {
          const payload = event.payload as StreamHello;
          setState({
            status: payload.status,
            snapshot: payload.snapshot,
            forecast: payload.forecast,
            latestForecast: payload.latest_forecast ?? null,
            serverTime: payload.server_time,
            transport: "open",
            lastEventAt: receivedAt,
          });
          return;
        }
        if (event.type === "market") {
          setState((previous) => ({
            ...previous,
            snapshot: event.payload,
            serverTime: new Date().toISOString(),
            lastEventAt: receivedAt,
          }));
          return;
        }
        if (event.type === "candle") {
          publishLiveCandle(event.payload);
          return;
        }
        if (event.type === "forecast") {
          setState((previous) => ({
            ...previous,
            latestForecast: event.payload,
            lastEventAt: receivedAt,
          }));
          return;
        }
        if (event.type === "status") {
          setState((previous) => ({
            ...previous,
            status: event.payload,
            lastEventAt: receivedAt,
          }));
          return;
        }
        setState((previous) => ({ ...previous, lastEventAt: receivedAt }));
      };

      socket.onerror = () => {
        socket.close();
      };

      socket.onclose = () => {
        if (disposed) return;
        socketRef.current = null;
        scheduleReconnect();
      };
    };

    const scheduleReconnect = () => {
      if (disposed) return;
      retryRef.current += 1;
      setState((previous) => ({ ...previous, transport: "reconnecting" }));
      const delay = Math.min(1000 * 2 ** Math.min(retryRef.current, 4), 12_000);
      clearTimer();
      timerRef.current = window.setTimeout(connect, delay);
    };

    connect();

    return () => {
      disposed = true;
      clearTimer();
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [enabled]);

  return state;
}
