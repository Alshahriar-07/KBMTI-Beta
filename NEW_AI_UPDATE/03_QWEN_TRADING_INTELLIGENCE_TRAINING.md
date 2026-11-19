# 03 — Qwen Trading Intelligence: Knowledge and Training Plan

## 1. Model role

Starting model: Qwen3-4B, used through the existing embedded llama.cpp runtime.

Target role: interpret structured market context and strategy candidates, explain a trade plan, manage conversational questions about the plan, and summarize verified outcomes.

It is not the source of truth for price calculations, indicator values, order state, or performance statistics.

## 2. Training sequence

### Stage A — Knowledge base first

Create curated, versioned documents for:
- market structure: swing highs/lows, HH/HL/LH/LL, BOS and CHoCH;
- trend, range and consolidation;
- momentum and momentum divergence;
- support/resistance and supply/demand zones;
- liquidity concepts and sweep confirmation;
- price action and candle formations;
- EMA, RSI, MACD, ATR, VWAP and volume interpretation;
- volatility and market regimes;
- strategy definitions and their exact entry/exit rules;
- position sizing, risk/reward and trade management;
- uncertainty, invalidation and no-trade conditions.

Each document should state definitions, assumptions, limitations, examples and source/provenance. Avoid treating disputed trading terminology as universal fact.

Use retrieval (RAG) to provide relevant knowledge at inference time. Include document IDs and version in internal traces.

### Stage B — Tool-grounded reasoning

Before fine-tuning, implement tools that return verified structured values:
- get_market_snapshot;
- get_indicator_snapshot;
- get_structure_snapshot;
- get_patron_forecast (read-only);
- list_strategy_candidates;
- calculate_trade_plan;
- validate_trade_plan;
- get_open_trade_state;
- get_trade_outcome;
- get_strategy_performance.

Use JSON schemas and strict authorization. Tools must have timeouts and bounded outputs.

### Stage C — Supervised fine-tuning dataset

Build examples from:
- expert-authored educational cases;
- deterministic strategy-engine outputs;
- historical market snapshots with leakage-safe labels;
- paper-trade reviews;
- carefully reviewed synthetic examples clearly marked as synthetic.

Do not blindly scrape social posts or copy unverified “profitable signals”. Do not treat every historical winning trade as a good decision or every losing trade as a bad decision.

### Stage D — LoRA experiment

Run a feasibility assessment separate from inference benchmarks. Determine supported training framework, GPU/CPU memory needs, batch size, sequence length, quantization compatibility, adapter format and export compatibility with the deployed runtime.

Do not assume the RX 580 Vulkan inference path supports efficient LoRA training. If local training is not viable, prepare a reproducible training environment on suitable hardware; inference can remain local.

Keep base weights unchanged. Version adapter, tokenizer, dataset manifest, training config and evaluation report.

### Stage E — Candidate evaluation

Compare:
- base Qwen + RAG + tools;
- candidate LoRA + same RAG + same tools.

Evaluate structured accuracy, evidence citation, tool selection, refusal/no-trade behavior, hallucination rate, latency and memory. A fine-tuned model must be measurably better on held-out cases and must not regress safety.

## 3. Training example format

Use a versioned JSONL schema. Example (illustrative only):

```json
{
  "schema_version": "1.0",
  "case_id": "case-example-001",
  "input": {
    "symbol": "BTCUSDT",
    "timeframe": "15m",
    "snapshot_ref": "snapshot-id",
    "market_context": {},
    "patron_forecast_ref": "forecast-id",
    "strategy_candidates_ref": "candidate-set-id"
  },
  "expected": {
    "action": "WAIT",
    "selected_strategy_id": null,
    "required_confirmation": ["example_confirmation"],
    "invalidation": ["example_invalidation"],
    "evidence_refs": ["snapshot-id"]
  },
  "label_metadata": {
    "label_source": "expert_review",
    "review_status": "approved",
    "is_synthetic": false,
    "split": "train"
  }
}
```

Do not use placeholder values as real training examples. Every actual example must have complete metadata and traceable source data.

## 4. What the model should learn

- Ask for missing context rather than guessing.
- Prefer WAIT/NO_TRADE when evidence is incomplete or conflicting.
- Separate observation, hypothesis and recommendation.
- State supporting and opposing evidence.
- Explain which condition confirms the setup and which condition invalidates it.
- Use tools for exact calculations.
- Never claim a probability is calibrated unless calibration has been measured.
- Never claim a trade is profitable or guaranteed.

## 5. Prompting and output

Use a strict JSON response schema with:
- action;
- market_regime;
- directional_bias;
- candidate_strategy_id;
- entry_plan_ref;
- risk_plan_ref;
- confirmation_conditions;
- invalidation_conditions;
- evidence_refs;
- uncertainty_notes;
- explanation.

The UI should render authoritative numeric fields from deterministic services, not parse numbers from free-form reasoning.

## 6. Model versioning

Record:
- base model ID and exact revision/hash;
- adapter ID/hash;
- tokenizer revision;
- dataset manifest hash;
- training code commit;
- hyperparameters and seed;
- evaluation report ID;
- runtime ABI and quantization format.

Never overwrite the current production model in place.
