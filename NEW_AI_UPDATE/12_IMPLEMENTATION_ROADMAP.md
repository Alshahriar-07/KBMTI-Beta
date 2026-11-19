# 12 — Implementation Roadmap

Implement in small phases. Do not combine all phases into one large change.

## Phase 0 — Repository audit and design lock

- Inspect actual KBMTI backend, UI, DI, API, chart and PATRON adapter.
- Read existing KIE plan and Phase A/Phase B reports.
- Confirm what Phase B actually implemented before extending it.
- Map existing modules to this plan; avoid duplicate abstractions.
- Produce a gap report and implementation task list.
- No code changes until the audit is reviewed.

**Exit:** architecture map, compatibility plan and test plan approved.

## Phase 1 — Market context and deterministic analysis

- Build validated snapshot contracts.
- Add trend, structure, momentum, volatility and regime features.
- Add freshness and provenance.
- Keep PATRON read-only.
- Unit-test each calculation against hand-checked fixtures.

**Exit:** reproducible analysis snapshots with complete tests.

## Phase 2 — Strategy registry and candidate engine

- Implement one strategy at a time.
- Add WAIT/NO_TRADE and rejection reasons.
- Version every rule.
- Add deterministic tests and historical harness.

**Exit:** candidates can be explained and rejected with evidence.

## Phase 3 — Risk and trade planner

- Implement entry/SL/TP methodology and position risk only with complete instrument/account inputs.
- Validate tick/lot constraints and fees.
- Add invalidation and expiry.
- No order execution.

**Exit:** all risk invariants and calculations pass.

## Phase 4 — Qwen intelligence integration

- Add RAG knowledge base.
- Add approved read-only tools.
- Add strict structured output and validator.
- Test base Qwen before fine-tuning.
- Compare model explanation to deterministic truth.

**Exit:** Qwen can interpret, explain and ask tools without inventing authoritative numbers.

## Phase 5 — Trading UI

- Add decision card, market context, plan overlay and next-action card.
- Add active/completed setup history.
- Add stale/unavailable/rejected states.
- Preserve current chart and PATRON visualization.

**Exit:** user can understand why a setup exists and what invalidates it.

## Phase 6 — Journal and outcome review

- Record setup snapshots and user actions.
- Track manual/paper trade lifecycle.
- Calculate R, MFE/MAE and costs.
- Add success/failure review with uncertainty labels.

**Exit:** complete auditable lifecycle from proposal to outcome.

## Phase 7 — Dataset and LoRA experiment

- Build leakage-safe dataset.
- Review labels.
- Assess local training feasibility.
- Run candidate LoRA experiment on suitable hardware.
- Compare against base Qwen + RAG + tools.

**Exit:** reproducible report with no production promotion.

## Phase 8 — Backtest and paper trading

- Walk-forward and untouched test.
- Cost-aware performance.
- Paper trading and monitoring.
- Predeclared release gates.

**Exit:** documented pass/fail decision.

## Phase 9 — Controlled promotion and monitoring

- Explicit model/strategy approval.
- Versioned deployment.
- Health metrics and drift alerts.
- Rollback tested.

**Exit:** safe, reversible assisted release.

## Critical implementation instruction

Do not start by fine-tuning Qwen. First establish data correctness, deterministic analysis, strategy rules, risk calculations, journaling and a baseline evaluation. Fine-tuning without reliable labels and evaluation can make the system more confident without making it more correct.
