import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DecisionCard } from "@/components/assistant/DecisionCard";
import type { TradingIntelligence } from "@/lib/types";

function data(overrides: Partial<TradingIntelligence> = {}): TradingIntelligence {
  return {
    request_id: "r1",
    generated_at: "2026-01-01T00:00:00Z",
    data_as_of: "2026-01-01T00:00:00Z",
    is_stale: false,
    snapshot_id: "s1",
    strategy_evaluation_id: "e1",
    plan_id: "p1",
    symbol: "BTCUSDT",
    timeframe: "M15",
    action: "LONG",
    plan_status: "PLAN_REVIEW_REQUIRED",
    execution_eligibility: "REVIEW_REQUIRED",
    strategy_validation_status: "PENDING",
    market_explanation: "Trend is aligned.",
    strategy_comparison: [],
    plan_explanation: "Geometry is hypothetical.",
    uncertainty: "The gate is pending.",
    next_action: "Human review is required.",
    evidence_refs: ["snapshot:s1"],
    knowledge_refs: [],
    knowledge: [],
    warnings: [],
    qwen: {
      used: false,
      status: "UNAVAILABLE",
      model: null,
      run_id: null,
      latency_ms: null,
      error: null,
      validation_notes: [],
    },
    position_size_status: "NOT_CALCULATED",
    position_size: null,
    execution: "DISABLED",
    disclaimer: "Not advice.",
    ...overrides,
  };
}

describe("DecisionCard", () => {
  it("renders the deterministic action and non-execution state", () => {
    render(<DecisionCard data={data()} />);
    expect(screen.getByText("LONG")).toBeInTheDocument();
    expect(screen.getByText("PLAN_REVIEW_REQUIRED")).toBeInTheDocument();
    expect(screen.getByText(/position size NOT_CALCULATED/i)).toBeInTheDocument();
    expect(screen.getByText(/no order exists/i)).toBeInTheDocument();
  });

  it("renders WAIT as a valid decision", () => {
    render(<DecisionCard data={data({ action: "WAIT", plan_status: "PLAN_BLOCKED" })} />);
    expect(screen.getByText("WAIT")).toBeInTheDocument();
  });
});
