import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PipelineReadinessPanel } from "@/components/assistant/PipelineReadinessPanel";
import type { PipelineReadiness } from "@/lib/types";

const readiness: PipelineReadiness = {
  market: {
    status: "READY",
    detail: "Verified BTCUSDT M15 snapshot from closed candles.",
    reason_code: "MARKET_READY",
    missing_inputs: [],
    data_as_of: "2026-11-22T10:00:00Z",
    freshness_seconds: 30,
  },
  patron: {
    status: "CONFLICTING",
    detail: "PATRON median path is BEARISH; assessment CONFLICTING_EVIDENCE.",
    reason_code: "CONFLICTING_EVIDENCE",
    missing_inputs: [],
    assessment: "CONFLICTING_EVIDENCE",
    usable_in_decision: false,
    conflicts: ["PATRON's median path is BEARISH while deterministic direction is BULLISH."],
    freshness_seconds: 30,
    median_path_atr: 0.42,
  },
  qwen: {
    status: "INITIALIZING",
    detail: "Qwen is initializing on the AMD Vulkan backend.",
    reason_code: "INITIALIZING",
    missing_inputs: [],
    health_state: "INITIALIZING",
    waited_seconds: 3.2,
  },
  strategy: {
    status: "PENDING",
    detail: "The independent human-reviewed acceptance gate is PENDING.",
    reason_code: "STRATEGY_GATE_PENDING",
    missing_inputs: [],
    reviewed_cases: null,
    required_cases: null,
  },
  trade_plan: {
    status: "UNAVAILABLE",
    detail: "No trade plan was constructed: Strategy decision is WAIT.",
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
    detail: "Position size is not calculated: verified account/risk inputs are missing.",
    reason_code: "MISSING_ACCOUNT_INPUTS",
    missing_inputs: ["account_balance_or_equity", "tick_value"],
  },
  execution: {
    status: "DISABLED",
    detail: "Order execution is disabled in this phase; no order can be placed.",
    reason_code: "EXECUTION_DISABLED",
    missing_inputs: [],
  },
};

describe("PipelineReadinessPanel", () => {
  it("reports each component separately while only Qwen is initializing", () => {
    render(<PipelineReadinessPanel readiness={readiness} />);

    expect(screen.getByText("Market analysis")).toBeInTheDocument();
    expect(screen.getByText("READY")).toBeInTheDocument();
    expect(screen.getByText("PATRON forecast")).toBeInTheDocument();
    expect(screen.getByText("CONFLICTING")).toBeInTheDocument();
    expect(screen.getByText("Qwen interpretation")).toBeInTheDocument();
    expect(screen.getByText("INITIALIZING")).toBeInTheDocument();
    expect(screen.getByText(/waited 3.20 s/)).toBeInTheDocument();
    expect(screen.getByText("Strategy validation")).toBeInTheDocument();
    expect(screen.getByText("PENDING")).toBeInTheDocument();
    expect(screen.getByText("Trade plan")).toBeInTheDocument();
    expect(screen.getByText("UNAVAILABLE")).toBeInTheDocument();
    expect(screen.getByText("NOT EVALUATED")).toBeInTheDocument();
    expect(screen.getByText("NOT CALCULATED")).toBeInTheDocument();
    expect(screen.getByText(/account_balance_or_equity, tick_value/)).toBeInTheDocument();
    expect(screen.getByText("DISABLED")).toBeInTheDocument();
    expect(screen.getByText(/reason: STRATEGY_WAIT/)).toBeInTheDocument();
  });
});
