# KIE — Phase B results

**Foundational integration inside the KBMTI backend (2026-11-19)**

Phase B builds the KIE that Phase A made possible: a model manager, request lifecycle,
reasoning policy, planner, workflow controller, tool-engine foundation, run persistence and
an additive `/api/v1/kie` namespace — with Qwen3-4B actually answering through it, and
`/api/v1/chat/*` untouched.

**Status: complete for the Phase B scope.** 152 backend tests pass (49 of them new KIE
tests plus the 7 Phase A runtime tests, one opt-in real-runtime smoke test), `ruff check app
tests scripts` is clean, and the real pinned runtime was exercised end-to-end through the
HTTP API on this machine.

Phase B is a foundation, not the finished product: no KBMTI tool is registered yet (Phase C),
the planner emits a single answer step (Phase D), and the chat responder is wired but dark
by default. Those are deliberate boundaries, listed in §8.

---

## 1. What exists now

```text
backend/app/kie/
  contracts.py        dataclasses/enums/Protocols: Mode, Access, ModelState, EventType, Message,
                      RunRequest, RunResult, GenerationStats, ModelInfo, MemoryBudget, KieEvent,
                      ToolSpec/Call/Result, Plan/PlanStep, EnginePort, ToolPort
  errors.py           KIE_* ApiError subclasses (503/429/507/422/404/403/504/500), retryable flag
  config.py           KieConfig + KBMTI_KIE_* environment, defaults measured in Phase A
  model_manager.py    one engine, backend selection + CPU fallback, budget enforcement from
                      llama.cpp buffer accounting, SingleFlight slot with a bounded queue
  reasoning.py        mode policy (fast/reasoning), system prompt, deterministic context block
  planner.py          goal → bounded Plan (one answer step in Phase B)
  workflow.py         step state machine: step budget, retries, duplicate-step loop guard
  core.py             run lifecycle: events, thinking/answer split, cancellation, timeout,
                      persistence, terminal event
  repository.py       kie_runs + kie_tool_calls persistence (additive tables)
  service.py          facade: status/load/unload/models/chat/stream/cancel/runs/tools
  responder.py        optional ChatResponder that falls back to RuleBasedResponder
  tools/registry.py   closed allow-list, JSON-Schema-subset validation, access levels
  tools/engine.py     execute with timeout, error capture and result truncation
  runtime/…           Phase A: ctypes shim + llama.cpp engine (unchanged)
```

Wiring (all additive):

| File | Change |
|---|---|
| `app/api/v1/kie.py` | new router |
| `app/api/v1/router.py` | one `include_router` line |
| `app/container.py` | `AppContainer.kie`, `KieService` construction, opt-in responder |
| `app/main.py` | `create_app(..., kie=...)`, `kie.startup()` / `kie.shutdown()` in the lifespan |
| `app/persistence/db.py` | two new tables, no existing table or column altered |
| `backend/pyproject.toml` | `kie_runtime` marker + opt-in collection for the slow smoke test |

No file under `PATRON/`, `PATROR/` or `app/patron/` was modified. `ChatService`,
`RuleBasedResponder` and the `/chat/*` schemas are unchanged.

---

## 2. Runtime policy actually implemented

| Setting | Default | Where it comes from |
|---|---|---|
| context | **4096** | Phase A measured 3 853 MiB of Vulkan buffers and ~12 s prefill at 8192; 4k is the honest default, overridable with `KBMTI_KIE_CTX` |
| batch / ubatch | 512 / 512 | Phase A batch sweep (256/1024/2048 changed prefill by ~10%) |
| backend order | `vulkan` → `cpu` | `KBMTI_KIE_BACKEND=auto\|vulkan\|cpu`; CPU is always the last resort |
| VRAM budget | 4096 MB | measured buffers only, never an OS estimate |
| RAM budget (CPU path) | 11 000 MB | leaves room for Windows, PATRON and the desktop app |
| Vulkan residual | 376 MB | Phase A unload measurement; carried in the budget, not ignored |
| single flight | 1 active, queue 3, 30 s wait | then `429 KIE_BUSY` |
| generation timeout | 120 s | checked per token |
| max tokens | 512 (hard cap 1024) | 1024 requires an explicit request |
| thinking | off (fast) | `mode=reasoning` or `thinking=true` opts in |
| autoload | off | `KBMTI_KIE_AUTOLOAD=1` warms in the background |

**Budget enforcement** uses llama.cpp's own accounting. At load time the manager parses the
`… buffer size = N MiB` lines, splits VRAM from host memory (`Vulkan_Host` and `CPU*` are
host), and compares model + KV + compute against the budget. If the GPU does not fit, it
computes the measured per-layer cost and retries with fewer offloaded layers; if the KV
cache and compute buffers alone exceed the budget, it unloads and falls back to CPU; if the
CPU build also does not fit, the load fails with `MODEL_LOAD_FAILED` and every attempt in
`details.attempts`. A load that reports no GPU device from the Vulkan runtime is rejected
outright rather than being recorded as GPU inference.

**Backend honesty.** `status.backend` is `vulkan` or `cpu`; `status.accelerated` is false for
CPU; `status.fallback_reason` names the failed backend; `status.identity` carries the
runtime tag, `llama_version`, device lines and the ggml `gpu_offload` flag. There is no code
path that reports CPU inference as GPU inference.

---

## 3. API

| Method | Path | Behaviour |
|---|---|---|
| GET | `/api/v1/kie/status` | state, backend, acceleration flag, identity, model, context, measured memory, queue, active runs, modes, tools, artifacts, config |
| GET | `/api/v1/kie/models` | manifest/runtime/model presence + pinned hashes |
| GET | `/api/v1/kie/tools` | registry (empty in Phase B, by design) |
| POST | `/api/v1/kie/load` | idempotent load; returns measured memory and fallback reason |
| POST | `/api/v1/kie/unload` | frees the context/model |
| POST | `/api/v1/kie/chat` | non-streaming run: `text`, `backend`, `mode`, `stats`, `finish`, `run_id` |
| POST | `/api/v1/kie/chat/stream` | SSE: `start` / `thinking` / `token` / `done` / `cancelled` / `error` |
| POST | `/api/v1/kie/cancel` | sets the run's cancel flag by `run_id` |
| GET | `/api/v1/kie/runs` | recent runs |
| GET | `/api/v1/kie/runs/{run_id}` | run + tool-call audit trail |

Errors use the existing envelope: `MODEL_NOT_LOADED` 503, `MODEL_LOADING` 503,
`KIE_DISABLED` 503, `KIE_BUSY` 429, `KIE_MEMORY_BUDGET` 507, `PROMPT_TOO_LONG` 422,
`KIE_VALIDATION_ERROR` 422, `RUN_NOT_FOUND` 404, `KIE_GENERATION_FAILED` 500.

Streaming is SSE per request (one connection, works in the Tauri webview without extra
plumbing). A stream is refused with `503 MODEL_NOT_LOADED` *before* the response starts, so
clients never get a 200 stream that immediately carries an error. If the client disconnects
mid-stream the generator's `finally` cancels the run.

---

## 4. Request lifecycle

```text
POST /kie/chat
  → parse + validate (mode, sizes, user message present)
  → prompt budget check (oversized single message → PROMPT_TOO_LONG, never a silent cut)
  → KieCore.run
      register run (cancel by id)
      plan (Planner → one answer step)
      workflow (step budget, loop guard, retry policy)
      ReasoningEngine: system prompt + CONTEXT block (data, not instructions)
      ModelManager.generate: single-flight slot → llama.cpp → on_token
      StreamFilter: thinking vs answer, fast-mode empty block dropped
      persist (status/finish/tokens/ttft/tok_s), emit terminal event
```

Cancellation is checked before every token and inside the engine (llama.cpp abort
callback). A cancelled run keeps the partial text, is stored as `cancelled`, and the context
is immediately reusable. A run that exceeds the wall-clock budget is cancelled the same way
but recorded as `finish=timeout` so it is not confused with a user cancel.

---

## 5. Measured on this machine (real runtime)

End-to-end through `create_app` + `TestClient` with the pinned b12503 Vulkan runtime and
Qwen3-4B Q4_K_M, `n_ctx=2048`, `vram_budget_mb=4096`:

| Step | Result |
|---|---|
| `POST /kie/load` | backend `vulkan`, `offloaded_layers` 37, measured buffers **2 982.7 MB**, load **2.17 s** |
| `POST /kie/chat` (192-token prompt) | `finish=stop`, TTFT **1 097 ms**, 41 tokens, **19.4 tok/s**, total 3 211 ms |
| `POST /kie/chat/stream` | 46 SSE events (`start` → 44 × `token` → `done`), text assembled from `token` events |
| `GET /kie/runs` | 2 persisted runs, both `status=done` |
| `POST /kie/unload` | state `unloaded` |

The answer itself was coherent and used the supplied context ("…in the BTC/USDT M15 market
over a specific period, based on historical data and probabilistic models."). At 4096
context the measured buffer total is ≈3.3 GB (model 2 375.91 + KV 576 + compute ~325 MiB),
which is why the 4 096 MB budget is the default and 8192 is not.

Two Phase A findings shaped the implementation: the KV cache must be cleared between
requests (already handled in `LlamaRuntime`), and Vulkan decode is asynchronous, so the
runtime times decode by wall clock rather than by call duration.

---

## 6. Tests

`backend/tests/`:

| File | Tests | Covers |
|---|---|---|
| `test_kie_core.py` | 37 | buffer parsing, load/unload/idempotency, disabled manager, CPU fallback, GPU-without-device rejection, identity, budget layer reduction, budget failure with attempts, single-flight serialisation, full-queue 429, run events/persistence, fast-mode thinking strip, reasoning-mode thinking events, cancellation, timeout, prompt budget, workflow loop guard/retries/plan bounds, planner shape, registry validation, tool access/timeout/truncation, request parsing, stream filter, autoload failure, degraded artifacts |
| `test_kie_api.py` | 12 | status shape, models/tools, 503 before load, request validation, load→chat→runs→404s, SSE frames, unload, disabled service, **existing `/chat/*` contract unchanged**, responder fallback/ready/empty-output |
| `test_kie_runtime.py` | 7 | Phase A shim guard rails (ABI sizes, manifest pins, thinking switch, batch layout) |
| `test_kie_runtime_smoke.py` | 1 (opt-in) | real model loads, identity is honest, one generation through `KieService`, run persisted, unload |

Default run: `152 passed, 1 deselected`. Real runtime:
`pytest -m kie_runtime tests/test_kie_runtime_smoke.py` → pass.

The fakes in `tests/kie_fakes.py` implement the same `EnginePort` as `LlamaRuntime`, so the
lifecycle/budget/queue logic is tested deterministically without a GPU — and the real engine
is covered by the opt-in smoke test instead of being mocked everywhere.

---

## 7. Compatibility and failure behaviour

- **`/chat/*` unchanged.** `ChatService` is not modified; its default responder is still
  `RuleBasedResponder`. `KieResponder` is only installed when
  `KBMTI_KIE_CHAT_RESPONDER=1`, and even then it falls back to the rules engine whenever KIE
  is disabled, unloaded, busy, cancelled or returns empty text. A regression test asserts the
  `responder` field and the `{user_message, assistant_message, context}` shape.
- **KIE cannot block startup.** The service is constructed without touching the model;
  autoload runs in a daemon thread and records failures; the lifespan wraps startup and
  shutdown in `try/except`. With no manifest, `status.available` is `false` and the reason is
  reported — the rest of KBMTI is unaffected.
- **Persistence is additive.** `kie_runs` and `kie_tool_calls` are created with
  `CREATE TABLE IF NOT EXISTS`; `chat_conversations`/`chat_messages` are untouched and no
  existing column changed. `table_counts()` still reports the original tables.

---

## 8. Deferred, and why

| Not in Phase B | Consequence today | Phase |
|---|---|---|
| KBMTI tool adapters (PATRON, market, system) | `/kie/tools` returns an empty registry; the engine/validation/audit machinery is tested with fake tools only | C |
| Tool calls in the chat loop | the model answers from the CONTEXT block; it cannot fetch | C |
| Multi-step planning, real tool routing | `Planner` emits one `answer` step | D |
| `/ws/kie` (load progress push) | SSE covers chat; load is a single request that returns when done | E |
| UI badge / mode switch / tool trace | desktop UI unchanged | E |
| `chat_messages.meta.kie_run_id` | KIE runs are stored separately; conversations keep their existing shape | E |
| Token-by-token reasoning stream | the thinking block is delivered as one `thinking` event at the end of the thinking phase | D |
| Cancelling during prompt prefill | cancel is observed between decode steps; a prefill in progress must finish | C |
| Timeout during prefill | the wall-clock budget is enforced per token, so prefill is not interruptible | C |
| Adapters / LoRA | no fine-tuning was attempted | F |

Honest limitations worth repeating: a 4B model at 19 tok/s with 3 s prefill is a *management*
assistant, not a chat replacement; reasoning mode spends the token budget on visible
thinking; and the VRAM measurement is only as good as llama.cpp's buffer report (the Windows
PDH counter saturates at 2 GB, as Phase A documented).

---

## 9. Reproduce

```bash
cd backend
# unit + API suite (fast, no model)
PYTHONPATH=. .venv/Scripts/python.exe -m pytest -q

# real runtime through the HTTP API (loads the 2.4 GB GGUF, needs the GPU)
PYTHONPATH=. .venv/Scripts/python.exe -m pytest -m kie_runtime tests/test_kie_runtime_smoke.py -q

# manual smoke of the running backend
curl -s localhost:8756/api/v1/kie/status | jq .
curl -s -X POST localhost:8756/api/v1/kie/load | jq '.backend, .memory'
curl -s -X POST localhost:8756/api/v1/kie/chat \
     -H 'content-type: application/json' \
     -d '{"message":"What is a volatility forecast?","mode":"fast"}' | jq '.text, .stats'
```

Configuration: `KBMTI_KIE_ENABLED`, `_AUTOLOAD`, `_BACKEND`, `_CTX`, `_BATCH`, `_GPU_LAYERS`,
`_VRAM_BUDGET_MB`, `_RAM_BUDGET_MB`, `_RESIDUAL_MB`, `_QUEUE_MAX`, `_QUEUE_WAIT_S`,
`_TIMEOUT_S`, `_LOAD_TIMEOUT_S`, `_MAX_TOKENS`, `_HARD_MAX_TOKENS`, `_TEMPERATURE`, `_TOP_P`,
`_HISTORY`, `_CHAT_RESPONDER`.
