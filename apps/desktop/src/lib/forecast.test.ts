import { describe, expect, it } from "vitest";

import { newestForecast } from "@/lib/forecast";
import type { ForecastRun } from "@/lib/types";

function run(id: string, createdAt: string, inputLastBarAt = 1_700_000_000): ForecastRun {
  return {
    id,
    provider: "patron",
    model_id: "patron-1.0.0",
    tokenizer_id: null,
    symbol: "BTC/USDT",
    timeframe: "M15",
    created_at: createdAt,
    input_last_bar_at: inputLastBarAt,
    input_candle_count: 96,
    horizon: 6,
    latency_ms: 12,
    runtime: "cpu",
    status: "ok",
    warnings: [],
  };
}

describe("newestForecast", () => {
  it("prefers a newer polled run over an older WebSocket run", () => {
    const socket = run("socket", "2026-11-18T07:45:01Z", 1_794_987_000);
    const polled = run("polled", "2026-11-18T08:00:51Z", 1_794_987_900);

    expect(newestForecast(socket, polled)?.id).toBe("polled");
    expect(newestForecast(polled, socket)?.id).toBe("polled");
  });

  it("prefers a newer WebSocket event over a stale polled response", () => {
    const stale = run("stale", "2026-11-18T07:45:01Z", 1_794_987_000);
    const event = run("event", "2026-11-18T08:00:51Z", 1_794_987_900);

    expect(newestForecast(stale, event)?.id).toBe("event");
  });

  it("uses the input bar as a deterministic tiebreaker", () => {
    const olderBar = run("older-bar", "2026-11-18T08:00:51Z", 1_794_987_000);
    const newerBar = run("newer-bar", "2026-11-18T08:00:51Z", 1_794_987_900);

    expect(newestForecast(olderBar, newerBar)?.id).toBe("newer-bar");
  });

  it("ignores missing and invalid timestamps in favour of a valid run", () => {
    const invalid = run("invalid", "not-a-date");
    const valid = run("valid", "2026-11-18T08:00:51Z");

    expect(newestForecast(null, invalid, undefined, valid)?.id).toBe("valid");
    expect(newestForecast(null, undefined)).toBeNull();
  });
});
