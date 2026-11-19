import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SignalDistribution } from "@/components/market/SignalDistribution";
import { buildSignalDistribution } from "@/lib/signal-distribution";
import type { ForecastQuantileStep, ForecastRun, Signal } from "@/lib/types";

const NOW = Date.parse("2026-11-17T12:00:00Z");

function signal(score: number, freshness = "fresh"): Signal {
  return {
    symbol: "BTCUSDT",
    timeframe: "M15",
    label: score > 0 ? "BUY BIAS" : "SELL BIAS",
    direction: score > 0 ? "long" : "short",
    score,
    generated_at: new Date(NOW - 20_000).toISOString(),
    data_as_of: null,
    freshness,
    supporting: [],
    conflicting: [],
    neutral: [],
    invalidation: [],
    metrics: {},
    warnings: [],
    source_candle_count: 120,
    engine: "rule-based-technical-v1",
    ai_available: false,
    ai_note: "PATRON forecasts are reported separately.",
    disclaimer: "Not financial advice.",
  };
}

function quantileStep(step: number, q10: number, q50: number, q90: number): ForecastQuantileStep {
  return {
    step,
    minutes_ahead: step * 15,
    high: { q10, q50, q90 },
    low: { q10, q50, q90 },
    close: { q10, q50, q90 },
  };
}

function forecast(
  createdAt: string,
  probabilities: Record<string, number>,
  status = "ok",
  rangeQuantiles: ForecastQuantileStep[] = [],
): ForecastRun {
  return {
    id: "run-1234567890",
    provider: "patron",
    model_id: "patron-1.0.0",
    tokenizer_id: null,
    symbol: "BTC/USDT",
    timeframe: "M15",
    created_at: createdAt,
    input_last_bar_at: 1_700_000_000,
    input_candle_count: 96,
    horizon: 6,
    latency_ms: 12,
    runtime: "cpu",
    status,
    warnings: [],
    output: {
      patron: {
        status: "OK",
        symbol: "BTC/USDT",
        as_of: createdAt,
        horizon_minutes: 90,
        model_version: "1.0.0",
        feature_version: "1",
        pattern_scores: {},
        barrier_probabilities: { tp_first: 0.4, sl_first: 0.35, timeout: 0.25 },
        range_quantiles: rangeQuantiles,
        momentum: {
          class_probabilities: probabilities,
          predicted_class: "sideways",
        },
        data_quality: {
          valid: true,
          closed_candles: 96,
          sequence_length: 96,
          warnings: [],
        },
      },
    },
  };
}

describe("buildSignalDistribution", () => {
  it("maps the rule-engine directional score to a split that totals 100", () => {
    const result = buildSignalDistribution(signal(-0.76), null, NOW);
    expect(result).not.toBeNull();
    expect(result?.source).toBe("rules");
    expect(result?.title).toBe("Directional signal strength");
    expect(result?.buy).toBe(12);
    expect(result?.sell).toBe(88);
    expect((result?.buy ?? 0) + (result?.sell ?? 0)).toBe(100);
    expect(result?.fresh).toBe(true);
    expect(result?.confidence).toBeNull();
  });

  it("uses PATRON momentum classes and rounds to one decimal without losing 100%", () => {
    const result = buildSignalDistribution(
      signal(-0.2),
      forecast("2026-11-17T11:55:00Z", {
        strong_bullish: 0.338,
        bullish: 0,
        sideways: 0,
        bearish: 0.662,
        strong_bearish: 0,
      }),
      NOW,
    );
    expect(result?.source).toBe("patron");
    expect(result?.title).toBe("Model bias distribution");
    expect(result?.buy).toBe(33.8);
    expect(result?.sell).toBe(66.2);
    expect((result?.buy ?? 0) + (result?.sell ?? 0)).toBe(100);
    expect(result?.fresh).toBe(true);
  });

  it("derives a bullish model bias from the forecast close quantiles", () => {
    const result = buildSignalDistribution(
      signal(-0.2),
      forecast(
        "2026-11-17T11:55:00Z",
        { strong_bearish: 0.8, bearish: 0.2 },
        "ok",
        [quantileStep(6, -0.01, 0.03, 0.06)],
      ),
      NOW,
    );
    expect(result?.source).toBe("patron");
    expect(result?.sourceLabel).toBe("PATRON 90m close path");
    expect(result?.buy).toBe(80);
    expect(result?.sell).toBe(20);
    expect((result?.buy ?? 0) + (result?.sell ?? 0)).toBe(100);
    expect(result?.derivation).toContain("q10/q50/q90");
  });

  it("derives a bearish model bias from the forecast close quantiles", () => {
    const result = buildSignalDistribution(
      signal(0.2),
      forecast(
        "2026-11-17T11:55:00Z",
        { strong_bullish: 0.8, bullish: 0.2 },
        "ok",
        [quantileStep(6, -0.06, -0.03, 0.01)],
      ),
      NOW,
    );
    expect(result?.buy).toBe(20);
    expect(result?.sell).toBe(80);
    expect((result?.buy ?? 0) + (result?.sell ?? 0)).toBe(100);
  });

  it("keeps a zero-median quantile path at 50/50 without random jitter", () => {
    const result = buildSignalDistribution(
      null,
      forecast("2026-11-17T11:55:00Z", {}, "ok", [quantileStep(6, -0.02, 0, 0.02)]),
      NOW,
    );
    expect(result?.buy).toBe(50);
    expect(result?.sell).toBe(50);
  });

  it("splits sideways probability evenly and normalises the classes", () => {
    const result = buildSignalDistribution(
      null,
      forecast("2026-11-17T11:55:00Z", {
        strong_bullish: 2,
        bullish: 0,
        sideways: 1,
        bearish: 0,
        strong_bearish: 1,
      }),
      NOW,
    );
    expect(result?.buy).toBe(62.5);
    expect(result?.sell).toBe(37.5);
  });

  it("prefers a fresh rule reading over a stale PATRON forecast", () => {
    const result = buildSignalDistribution(
      signal(0.4),
      forecast("2026-11-17T09:00:00Z", { strong_bullish: 1 }),
      NOW,
    );
    expect(result?.source).toBe("rules");
    expect(result?.fresh).toBe(true);
  });

  it("marks PATRON output stale when no rule reading exists", () => {
    const result = buildSignalDistribution(
      null,
      forecast("2026-11-17T09:00:00Z", { bullish: 0.7, bearish: 0.3 }),
      NOW,
    );
    expect(result?.source).toBe("patron");
    expect(result?.fresh).toBe(false);
    expect(result?.freshnessLabel).toBe("Stale forecast");
  });

  it("returns null when neither source is available", () => {
    expect(buildSignalDistribution(null, null, NOW)).toBeNull();
  });

  it("does not turn an unavailable market feed into a neutral 50/50 split", () => {
    expect(buildSignalDistribution(signal(0, "unavailable"), null, NOW)).toBeNull();
  });
});

describe("SignalDistribution", () => {
  it("shows BUY/SELL percentages as the primary element", () => {
    render(<SignalDistribution signal={signal(-0.76)} forecast={null} />);
    expect(screen.getByText("12.0%")).toBeInTheDocument();
    expect(screen.getByText("88.0%")).toBeInTheDocument();
    expect(screen.getByText(/BUY 12\.0% · SELL 88\.0%/)).toBeInTheDocument();
    expect(screen.getByText("SELL")).toBeInTheDocument();
    expect(screen.getByText("Directional signal strength")).toBeInTheDocument();
    expect(
      screen.getByText("SELL pressure is dominant; BUY pressure is limited."),
    ).toBeInTheDocument();
  });

  it("withholds the split when no valid source exists", () => {
    render(<SignalDistribution signal={null} forecast={null} />);
    expect(screen.getByText("Signal unavailable")).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });
});
