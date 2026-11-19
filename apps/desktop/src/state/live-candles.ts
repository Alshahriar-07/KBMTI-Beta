import { useSyncExternalStore } from "react";

import type { Candle, StreamCandleEvent } from "@/lib/types";

/**
 * Tiny external store for the high-frequency Binance candle frames.
 *
 * Keeping this outside React context means a 4 Hz forming-candle update only
 * re-renders the chart and preview consumers, not the whole dashboard.
 */
let latest: StreamCandleEvent | null = null;
const listeners = new Set<() => void>();

function sameFrame(a: StreamCandleEvent, b: StreamCandleEvent): boolean {
  const left: Candle = a.candle;
  const right: Candle = b.candle;
  return (
    a.symbol === b.symbol &&
    a.timeframe === b.timeframe &&
    a.closed === b.closed &&
    left.time === right.time &&
    left.open === right.open &&
    left.high === right.high &&
    left.low === right.low &&
    left.close === right.close &&
    left.tick_volume === right.tick_volume
  );
}

export function publishLiveCandle(frame: StreamCandleEvent): void {
  if (latest && sameFrame(latest, frame)) return;
  latest = frame;
  for (const listener of listeners) listener();
}

export function getLiveCandle(): StreamCandleEvent | null {
  return latest;
}

export function subscribeLiveCandles(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useLiveCandle(): StreamCandleEvent | null {
  return useSyncExternalStore(subscribeLiveCandles, getLiveCandle, getLiveCandle);
}
