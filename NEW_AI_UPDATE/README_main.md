# KBMTI AI Trading Intelligence Upgrade — Documentation Pack

**Plan version:** 1.0  
**Date:** 2026-11-19  
**Scope:** AI intelligence, strategy education/training, trade-assistance UI, outcome tracking, failure analysis, and controlled retraining.

## Purpose

Upgrade KBMTI from a candle-forecast display into an AI-assisted market-analysis and trade-management application, while preserving PATRON as a separate candle-forecasting system.

This plan is an engineering specification, not a promise of profitable trades. No model can guarantee profit. The objective is to build a measurable, risk-aware assistant whose decisions can be audited, tested, and rejected when evidence is weak.

## Read first

1. `01_MASTER_UPDATE_PLAN.md` — overall product direction and non-negotiable boundaries.
2. `02_TARGET_ARCHITECTURE.md` — component responsibilities and data flow.
3. `03_QWEN_TRADING_INTELLIGENCE_TRAINING.md` — knowledge, RAG, LoRA and model lifecycle.
4. `04_DATASET_AND_LABELING_SPEC.md` — training/evaluation data requirements.
5. `05_STRATEGY_ENGINE_SPEC.md` — strategy definitions and setup generation.
6. `06_TRADE_RISK_AND_MANAGEMENT_SPEC.md` — entry, stop, targets, sizing and trade management.
7. `07_TRADING_UI_UX_SPEC.md` — UI changes and user workflow.
8. `08_TRADE_OUTCOME_AND_FAILURE_ANALYSIS.md` — completed-trade review and failure diagnosis.
9. `09_CONTINUOUS_LEARNING_AND_RETRAINING.md` — safe retraining pipeline.
10. `10_BACKTESTING_AND_RELEASE_GATES.md` — evidence required before enabling signals.
11. `11_API_AND_EVENT_CONTRACTS.md` — proposed additive contracts.
12. `12_IMPLEMENTATION_ROADMAP.md` — implementation order.
13. `13_SAFETY_AND_PERMISSION_RULES.md` — permissions, safety and operational limits.
14. `14_ACCEPTANCE_TESTS.md` — definition of done.

## Existing project constraints carried into this plan

- PATRON remains the existing quantitative candle-prediction model. Do not convert it into a strategy model or change its forecasting objective as part of this upgrade.
- Qwen3-4B is the selected starting intelligence model. The existing embedded llama.cpp runtime is the inference path; do not introduce Ollama, a llama-server subprocess, a cloud dependency, or a separate inference server.
- The current machine has an AMD RX 580 8GB. Phase A established Vulkan GPU offload, but the device lacks several modern acceleration features and long-context prefill is slow. Keep context and VRAM budgets conservative.
- Do not assume that inference capability means local LoRA training is feasible. Training hardware/runtime must be assessed separately.
- Preserve existing deterministic chat and current APIs. Add new endpoints and UI capabilities additively.
- Do not modify PATRON training/forecasting code without a separately approved change.
- The LLM must not invent prices, indicators, order status, backtest metrics, or trade outcomes. Numeric calculations and risk checks belong in deterministic, tested services.

## Global rule

A signal is a hypothesis with explicit invalidation, not a guarantee. `WAIT` and `NO_TRADE` are valid first-class decisions. Never optimize only for win rate; include expectancy, profit factor, drawdown, costs, calibration and out-of-sample performance.
