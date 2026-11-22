import { describe, expect, it } from "vitest";

import { DEFAULT_OVERLAY_LAYERS, buildTradeChartOverlay } from "@/lib/trade-visual";
import type { Candle, MarketIntelligence, MarketScenario } from "@/lib/types";

const candles: Candle[] = [
  {
    time: 1_700_000_000,
    open: 99,
    high: 101,
    low: 98,
    close: 100,
    tick_volume: 10,
    spread: 1,
    real_volume: 10,
  },
];

const scenario: MarketScenario = {
  id: "bullish_continuation",
  title: "Bullish continuation",
  bias: "BULLISH",
  available: true,
  condition: "Price is below resistance 103.",
  trigger: 103,
  target: 106,
  invalidation: 97,
  confirmation: "A closed candle above 103.",
  invalidation_text: "A close below 97 invalidates.",
  evidence_for: ["Trend is BULLISH."],
  evidence_against: ["Momentum is BEARISH."],
  unavailable_reason: null,
  structure: "UPTREND",
  data_as_of: "2026-11-22T10:00:00Z",
  data_is_stale: false,
  path: [
    { offset_bars: 1, price: 103 },
    { offset_bars: 3, price: 106 },
  ],
};

function intelligence(): MarketIntelligence {
  return {
    request_id: "req",
    generated_at: "2026-11-22T10:00:00Z",
    data_as_of: "2026-11-22T10:00:00Z",
    is_stale: false,
    symbol: "BTCUSDT",
    timeframe: "M15",
    market_snapshot: { last_price: 100 },
    market_condition: {
      trend: "BULLISH",
      trend_strength: "MODERATE",
      trend_alignment: "BULLISH_STACK",
      structure: "UPTREND",
      momentum: "BULLISH",
      momentum_phase: "STEADY",
      volatility: "NORMAL",
      volatility_phase: "STABLE",
      regime: "TRENDING_UP",
      direction: "BULLISH",
      summary: "Trend is bullish.",
    },
    chart_overlay: {
      levels: [
        {
          id: "level:support:1",
          kind: "SUPPORT",
          price: 97,
          label: "Support 1",
          touches: 3,
          time: "2026-11-22T09:00:00Z",
          detail: "Three verified swing touches.",
        },
        {
          id: "level:resistance:2",
          kind: "RESISTANCE",
          price: 106,
          label: "Resistance 2",
          touches: 2,
          time: "2026-11-22T09:15:00Z",
          detail: "Two verified swing touches.",
        },
      ],
      structure: [
        {
          id: "structure:1:BOS_UP",
          kind: "BOS_UP",
          price: 101,
          time: "2026-11-22T09:30:00Z",
          label: "BOS_UP",
          detail: "Confirmed break.",
          direction: "BULLISH",
        },
      ],
      scenarios: [scenario],
      method_note: "Deterministic.",
    },
    forecast_source: {
      provider: "patron",
      model_id: "patron",
      model_version: "1.0.0",
      checkpoint: null,
      checkpoint_sha256: null,
      feature_version: "features",
      generated_at: new Date(1_700_000_000 * 1000).toISOString(),
      forecast_as_of: new Date(1_700_000_000 * 1000).toISOString(),
      input_last_bar_at: new Date(1_700_000_000 * 1000).toISOString(),
      horizon_candles: 2,
      horizon_minutes: 30,
      reference_close: 100,
      predicted_candles: [
        {
          sequence: 0,
          timestamp_utc: 1_700_000_900,
          open: 100,
          high: 101.5,
          low: 99.5,
          close: 101,
        },
        {
          sequence: 1,
          timestamp_utc: 1_700_001_800,
          open: 101,
          high: 102.5,
          low: 100.5,
          close: 102,
        },
      ],
      range_quantiles: [
        {
          step: 1,
          minutes_ahead: 15,
          high: { q10: 0, q50: 0.01, q90: 0.02 },
          low: { q10: -0.02, q50: -0.01, q90: 0 },
          close: { q10: 0, q50: 0.01, q90: 0.02 },
        },
        {
          step: 2,
          minutes_ahead: 30,
          high: { q10: 0, q50: 0.02, q90: 0.03 },
          low: { q10: -0.03, q50: -0.02, q90: 0 },
          close: { q10: 0.01, q50: 0.02, q90: 0.03 },
        },
      ],
      barrier_probabilities: {},
      momentum: {},
      data_quality: {},
      source_hash: "hash",
      freshness_seconds: 0,
    },
    forecast_assessment: {
      status: "VALID",
      reasons: [],
      conflicts: [],
      usable_in_decision: true,
      confidence_score: null,
      freshness_seconds: 0,
      interval_width_atr: 1,
      barrier_margin: null,
      momentum_margin: null,
      forecast_direction: "BULLISH",
      deterministic_direction: "BULLISH",
      median_path_atr: 0.4,
      direction_conflict_material: true,
      horizon_minutes: 90,
    },
    ai_market_interpretation: "Market view.",
    ai_forecast_interpretation: "Forecast view.",
    bullish_evidence: [],
    bearish_evidence: [],
    strategy_candidates: [],
    readiness: {
      market: {
        status: "READY",
        detail: "Verified BTCUSDT M15 snapshot.",
        reason_code: "MARKET_READY",
        missing_inputs: [],
        data_as_of: "2026-11-22T10:00:00Z",
        freshness_seconds: 10,
      },
      patron: {
        status: "AVAILABLE",
        detail: "PATRON forecast is usable.",
        reason_code: "VALID",
        missing_inputs: [],
        assessment: "VALID",
        usable_in_decision: true,
        conflicts: [],
        freshness_seconds: 10,
        median_path_atr: 0.4,
      },
      qwen: {
        status: "READY",
        detail: "Qwen returned a validated interpretation.",
        reason_code: "USED",
        missing_inputs: [],
        health_state: "READY",
        waited_seconds: null,
      },
      strategy: {
        status: "PENDING",
        detail: "The independent acceptance gate is PENDING.",
        reason_code: "STRATEGY_GATE_PENDING",
        missing_inputs: [],
        reviewed_cases: null,
        required_cases: null,
      },
      trade_plan: {
        status: "AVAILABLE",
        detail: "A review-gated plan exists.",
        reason_code: null,
        missing_inputs: [],
        plan_status: "PLAN_REVIEW_REQUIRED",
      },
      risk: {
        status: "APPROVED",
        detail: "Risk checks approved the geometry.",
        reason_code: null,
        missing_inputs: [],
      },
      position_size: {
        status: "NOT_CALCULATED",
        detail: "Verified account inputs are missing.",
        reason_code: "MISSING_ACCOUNT_INPUTS",
        missing_inputs: ["account_balance_or_equity"],
      },
      execution: {
        status: "DISABLED",
        detail: "Order execution is disabled.",
        reason_code: "EXECUTION_DISABLED",
        missing_inputs: [],
      },
    },
    decision: "LONG",
    decision_reason: "Plan is eligible.",
    trade_plan: {
      plan_id: "plan-1",
      strategy_id: "trend_pullback",
      strategy_version: "1.0.0",
      direction: "LONG",
      plan_status: "PLANNED",
      entry_zone: { lower: "99", upper: "101", anchor: "100", anchor_type: "ema" },
      suggested_entry: "100",
      confirmation_level: "101",
      stop_loss: "98",
      stop_basis: "below swing low",
      take_profits: [
        { label: "TP1", price: "103", risk_multiple: "1.5", method: "atr" },
        { label: "TP2", price: "105", risk_multiple: "2", method: "level" },
        { label: "TP3", price: "108", risk_multiple: "3", method: "range" },
      ],
      risk_reward: { rr_tp1: "1.5", rr_tp2: "2", rr_tp3: "3" },
      invalidation_conditions: ["Close below 98."],
      confirmation_requirements: ["Close above 101."],
      expires_at: "2026-11-22T11:00:00Z",
      risk_validation_status: "PASSED",
      execution_eligibility: "REVIEW_REQUIRED",
    },
    risk_validation: {
      status: "PASSED",
      execution_eligibility: "REVIEW_REQUIRED",
      checks: [],
      position_size_status: "NOT_CALCULATED",
      position_size: null,
    },
    invalidation_conditions: [],
    data_freshness: {},
    model_versions: {},
    evidence_refs: [],
    warnings: [],
    unavailable_fields: [],
    ai_status: {
      used: true,
      status: "USED",
      model: "Qwen",
      run_id: "run",
      latency_ms: 1,
      error: null,
      validation_notes: [],
    },
    execution: "DISABLED",
    position_size_status: "NOT_CALCULATED",
    position_size: null,
    disclaimer: "No execution.",
  };
}

describe("buildTradeChartOverlay", () => {
  it("uses the exact deterministic plan prices for lines and bands", () => {
    const overlay = buildTradeChartOverlay(intelligence(), candles, DEFAULT_OVERLAY_LAYERS);
    const byId = new Map(overlay.lines.map((line) => [line.id, line]));

    expect(byId.get("suggested-entry")?.price).toBe(100);
    expect(byId.get("confirmation-level")?.price).toBe(101);
    expect(byId.get("stop-loss")?.price).toBe(98);
    expect(byId.get("target-3")?.price).toBe(108);
    expect(overlay.bands.find((band) => band.id === "risk-band")).toMatchObject({
      lower: 98,
      upper: 100,
    });
    expect(overlay.bands.find((band) => band.id === "reward-band")).toMatchObject({
      lower: 100,
      upper: 108,
    });
  });

  it("drops trade layers and markers when their toggles are off", () => {
    const overlay = buildTradeChartOverlay(intelligence(), candles, {
      ...DEFAULT_OVERLAY_LAYERS,
      trade: false,
      structure: false,
    });
    expect(overlay.lines.some((line) => line.id === "suggested-entry")).toBe(false);
    expect(overlay.bands).toHaveLength(0);
    expect(overlay.markers).toHaveLength(0);
  });

  it("draws only scenario paths from verified levels when enabled", () => {
    const overlay = buildTradeChartOverlay(intelligence(), candles, {
      ...DEFAULT_OVERLAY_LAYERS,
      scenarios: true,
    });
    const path = overlay.paths.find((item) => item.id === "scenario-bullish_continuation");
    expect(path?.points).toEqual([
      { time: 1_700_000_000, price: 100 },
      { time: 1_700_000_900, price: 103 },
      { time: 1_700_002_700, price: 106 },
    ]);
  });

  it("projects the stored PATRON median without inventing candles", () => {
    const overlay = buildTradeChartOverlay(intelligence(), candles, DEFAULT_OVERLAY_LAYERS);
    const path = overlay.paths.find((item) => item.id === "patron-median");
    expect(path?.points.map((point) => point.price)).toEqual([100, 101, 102]);
    expect(path?.points[1]?.time).toBe(1_700_000_900);
    expect(path?.points[2]?.time).toBe(1_700_001_800);
    expect(overlay.predictedCandles.map((candle) => candle.close)).toEqual([101, 102]);
    expect(overlay.predictedCandles[0]?.high).toBe(101.5);
  });
});
