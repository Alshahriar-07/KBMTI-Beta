import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AiIntelligencePanel } from "@/components/market/AiIntelligencePanel";
import type { MarketIntelligence } from "@/lib/types";

function intelligence(overrides: Partial<MarketIntelligence> = {}): MarketIntelligence {
  return {
    request_id: "req-1",
    generated_at: "2026-11-22T10:00:00Z",
    data_as_of: "2026-11-22T10:00:00Z",
    is_stale: false,
    symbol: "BTCUSDT",
    timeframe: "M15",
    market_snapshot: {},
    chart_overlay: {
      levels: [],
      structure: [],
      scenarios: [],
      method_note: "Deterministic chart annotations.",
    },
    market_condition: {
      trend: "BULLISH",
      trend_strength: "MODERATE",
      trend_alignment: "BULLISH_STACK",
      structure: "UPTREND",
      momentum: "BEARISH",
      momentum_phase: "DECELERATING",
      volatility: "NORMAL",
      volatility_phase: "STABLE",
      regime: "TRENDING_UP",
      direction: "BULLISH",
      summary: "Regime TRENDING_UP; trend BULLISH.",
    },
    forecast_source: {
      provider: "patron",
      model_id: "patron-1.0.0",
      model_version: "1.0.0",
      checkpoint: "best.pt",
      checkpoint_sha256: "abc",
      feature_version: "features-1.0.0",
      generated_at: "2026-11-22T10:00:00Z",
      forecast_as_of: "2026-11-22T10:00:00Z",
      input_last_bar_at: "2026-11-22T09:00:00Z",
      horizon_candles: 6,
      horizon_minutes: 90,
      reference_close: 95000,
      range_quantiles: [],
      predicted_candles: [],
      barrier_probabilities: { tp_first: 0.45, sl_first: 0.3, timeout: 0.25 },
      momentum: { predicted_class: "bearish" },
      data_quality: {},
      source_hash: "hash",
      freshness_seconds: 0,
    },
    forecast_assessment: {
      status: "CONFLICTING_EVIDENCE",
      reasons: ["PATRON median path conflicts with deterministic direction."],
      conflicts: ["PATRON is bearish; deterministic direction is bullish."],
      usable_in_decision: false,
      confidence_score: null,
      freshness_seconds: 0,
      interval_width_atr: 2.4,
      barrier_margin: 0.45,
      momentum_margin: 0.3,
      forecast_direction: "BEARISH",
      deterministic_direction: "BULLISH",
      median_path_atr: 0.4,
      direction_conflict_material: true,
      horizon_minutes: 90,
    },
    ai_market_interpretation: "The deterministic trend is bullish while momentum is bearish.",
    ai_forecast_interpretation: "PATRON conflicts with the deterministic direction and is excluded.",
    bullish_evidence: ["Deterministic trend is BULLISH."],
    bearish_evidence: ["Momentum is BEARISH."],
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
        status: "CONFLICTING",
        detail: "PATRON conflicts with the deterministic direction.",
        reason_code: "CONFLICTING_EVIDENCE",
        missing_inputs: [],
        assessment: "CONFLICTING_EVIDENCE",
        usable_in_decision: false,
        conflicts: ["PATRON is bearish; deterministic direction is bullish."],
        freshness_seconds: 0,
        median_path_atr: 0.4,
      },
      qwen: {
        status: "FAILED",
        detail: "Qwen is not loaded.",
        reason_code: "UNAVAILABLE",
        missing_inputs: [],
        health_state: "INITIALIZING",
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
        status: "UNAVAILABLE",
        detail: "No trade plan was constructed: strategy decision is WAIT.",
        reason_code: "STRATEGY_WAIT",
        missing_inputs: [],
        plan_status: "PLAN_BLOCKED",
      },
      risk: {
        status: "NOT_EVALUATED",
        detail: "Risk checks were not evaluated because no plan was constructed.",
        reason_code: "NO_PLAN_TO_ASSESS",
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
    decision: "WAIT",
    decision_reason: "No eligible candidate.",
    trade_plan: null,
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
    evidence_refs: ["snapshot:abc", "forecast.assessment"],
    warnings: ["PATRON assessment CONFLICTING_EVIDENCE."],
    unavailable_fields: ["position_size"],
    ai_status: {
      used: false,
      status: "UNAVAILABLE",
      model: null,
      run_id: null,
      latency_ms: null,
      error: "Qwen is not loaded.",
      validation_notes: [],
    },
    execution: "DISABLED",
    position_size_status: "NOT_CALCULATED",
    position_size: null,
    disclaimer: "Deterministic analysis is authoritative.",
    ...overrides,
  };
}

describe("AiIntelligencePanel", () => {
  it("shows the shared decision, forecast assessment and AI failure state", () => {
    render(<AiIntelligencePanel intelligence={intelligence()} />);
    expect(screen.getByText("WAIT")).toBeInTheDocument();
    expect(screen.getByText(/forecast conflicting evidence/i)).toBeInTheDocument();
    expect(screen.getByText(/excluded from decision/i)).toBeInTheDocument();
    expect(screen.getByText(/qwen is not loaded/i)).toBeInTheDocument();
  });

  it("renders explicit loading and unavailable states without fake values", () => {
    const { rerender } = render(<AiIntelligencePanel intelligence={null} loading />);
    expect(screen.getByText(/building the unified/i)).toBeInTheDocument();
    rerender(<AiIntelligencePanel intelligence={null} error="backend unreachable" />);
    expect(screen.getByText(/unified intelligence is unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/backend unreachable/i)).toBeInTheDocument();
    expect(screen.queryByText(/\$95,000/)).not.toBeInTheDocument();
  });
});
