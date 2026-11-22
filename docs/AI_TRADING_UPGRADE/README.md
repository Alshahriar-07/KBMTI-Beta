# KBMTI AI Trading Upgrade — documentation index

**Plan version:** 1.0 (from `NEW_AI_UPDATE/`)
**Last updated:** 2026-11-22
**Scope:** AI market intelligence, strategy evaluation, trade planning, risk, journal,
outcome review and controlled learning — while preserving PATRON, the existing chat and
the existing API/UI contracts. No automatic order execution exists or will be added here.

## Status

| Phase | Scope | Status |
|---|---|---|
| 0 | Repository audit, architecture map, gap analysis, task plan | **Complete** — approved as the baseline |
| 1 | Market intelligence foundation: BTCUSDT M15 snapshot, trend, structure, momentum, volatility, regime, liquidity, persistence, two read-only endpoints | **Complete, pending gate review** |
| 2 | Strategy registry and candidate engine (`trend_pullback` first) | **Implementation complete** — 60-case gate PENDING |
| 3 | Trade planner, validation and risk engine | **Complete, acceptance recommended** — strategy gate PENDING |
| 4 | Qwen trading intelligence: read-only tools, validator, deterministic retrieval | Not started |
| 5 | AI trading assistant UI and chart overlays | Not started |
| 6 | Trade journal, lifecycle and monitoring | Not started |
| 7 | Outcome and failure analysis | Not started |
| 8 | Dataset builder, walk-forward evaluation, backtesting | Not started |
| 9 | LoRA feasibility, evaluation, promotion and rollback | Not started |

## Documents

| Document | Purpose |
|---|---|
| [`REPOSITORY_AUDIT.md`](REPOSITORY_AUDIT.md) | Verified capability inventory, defects, constraints, preservation rules |
| [`EXISTING_ARCHITECTURE.md`](EXISTING_ARCHITECTURE.md) | Runtime topology, DI, data flows, schema/migration conventions, extension seams |
| [`IMPLEMENTATION_GAP_ANALYSIS.md`](IMPLEMENTATION_GAP_ANALYSIS.md) | Target-vs-actual mapping, contracts, DB/API/UI changes, risks, sequence |
| [`IMPLEMENTATION_TASKS.md`](IMPLEMENTATION_TASKS.md) | Phase task list, gates, test matrices, deferred backlog |
| [`PHASE_0_RESULTS.md`](PHASE_0_RESULTS.md) | Audit completion report and approved decisions |
| [`PHASE_1_RESULTS.md`](PHASE_1_RESULTS.md) | Market intelligence implementation, tests, measurements, limitations |
| [`PHASE_2_RESULTS.md`](PHASE_2_RESULTS.md) | Strategy engine implementation, rules, tests, provisional evaluation, PENDING gate |
| [`PHASE_2_EVALUATION.json`](PHASE_2_EVALUATION.json) | Provisional historical metrics and the 60 exported (unreviewed) gate cases |
| [`PHASE_3_RESULTS.md`](PHASE_3_RESULTS.md) | Trade geometry, risk policy, lifecycle, API, persistence, tests, measurements, acceptance |

## Approved decisions (locked)

1. Market scope is **BTCUSDT M15 only**; other scopes return an explicit unsupported state.
2. Package layout: `app/analysis`, `app/strategies`, `app/trade_planning`, `app/risk`,
   `app/intelligence`, `app/trade_journal`, `app/outcomes`, `app/learning`.
3. Position sizing stays `not_calculated`; account balance/equity/contract size are never invented.
4. First strategy is `trend_pullback`; `breakout_retest` waits for its 60-case gate.
5. Git was initialized and a baseline commit was created before implementation.
6. Retrieval is versioned in-repository text with deterministic matching; no vector database.
7. `app/evaluation` repair is deferred to Phase 8 unless an earlier phase needs it.
8. LoRA training must use a separate environment; no training dependency is added to backend requirements.

## Running the checks

```bash
cd backend
PYTHONPATH=. .venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check app tests scripts
```

The real-model KIE test remains opt-in (`-m kie_runtime`) and is not part of Phases 1–3.
The provisional strategy evaluation is separate and read-only:

```bash
cd backend
PYTHONPATH=. .venv/Scripts/python.exe scripts/evaluate_trend_pullback.py
```

## Non-negotiable boundaries

- PATRON (`PATRON/`, `backend/app/patron/`) is unchanged; analysis only reads its outputs later, through adapters.
- `/api/v1/chat/*` and all pre-existing endpoints keep their current contracts.
- No Ollama, llama-server, cloud inference, shell execution, broker orders or account fabrication.
- `WAIT`/`NO_TRADE` are valid outcomes; stale, invalid or insufficient data never produces a fabricated analysis.
