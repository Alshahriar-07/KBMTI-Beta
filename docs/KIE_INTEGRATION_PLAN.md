# KIE — KBMTI Intelligence Engine

**Architecture and integration plan (v1, 2026-11-18)**

Scope: a locally hosted, in-process language-model engine (Qwen3-4B, Apache-2.0) that turns the
existing PATRON-grounded deterministic assistant into a tool-using management engine, running on
the target workstation without Ollama, without a cloud API, and without an external model server.

**Status (2026-11-19):** Phase A (runtime bring-up) and Phase B (core + ModelManager +
`/api/v1/kie` foundation) are implemented and validated — see `docs/KIE_PHASE_A_RESULTS.md`
and `docs/KIE_PHASE_B_RESULTS.md`. Phases C–F are not started. The sections below are the
plan; where implementation differed, the results documents record the deviation.

Every claim about the pre-existing system below was read from the repository, not assumed.

---

## 1. Current architecture (verified)

```text
kbmti/ (PySide6 desktop launcher, 1.2k LOC)
  └─ spawns → backend/ (FastAPI on 127.0.0.1:8756, uvicorn)
                ├─ app/main.py            create_app(): lifespan starts market poll, PATRON autoload,
                │                         ForecastAutomation; routers + /ws/market
                ├─ app/container.py       build_container(): single composition root, AppContainer dataclass
                ├─ app/api/v1/            health, market, indicators, signals, forecast, patron, chat,
                │                         replay, diagnostics, system, settings, mt5
                ├─ app/api/ws.py          /ws/market — server→client only, Broadcast/queue based
                ├─ app/chat/service.py    ChatService + RuleBasedResponder (template text, no model)
                ├─ app/forecasting/       ForecastService (history/get_run/latest/timeline/evaluate/run_forecast)
                ├─ app/patron/            PatronInferenceService (torch CPU PATRON checkpoint, status/info/health)
                ├─ app/market_data/       MarketDataService, Binance provider + history client, MT5 gateway
                ├─ app/signals/           SignalService (rule-based bias)
                ├─ app/system/monitor.py  psutil CPU/RAM/process telemetry
                └─ app/persistence/       SQLite via Database + repositories (candles, signals, forecasts,
                                          chat conversations/messages, settings)
apps/desktop/ (Tauri + React + Vite + Tailwind) — pages: Overview, MarketChart, Signals,
  ForecastHistory, Chat, Replay, Diagnostics, Settings; talks only to the local backend.
```

Existing chat contract (must keep working):

- `POST /api/v1/chat/conversations/{id}/messages` → `{user_message, assistant_message, context}`,
  non-streaming, synchronous, persisted in SQLite.
- `ChatService` depends on a `ChatResponder` **Protocol** (`responder_id`, `respond(question, context) -> str`)
  and a `ChatContext` dataclass carrying snapshot, candles, signal, PATRON status, latest forecast
  and the last 8 messages. `RuleBasedResponder` is the only implementation today.
- `context.ai_available` is already surfaced to the UI and is currently `patron.ready AND latest_forecast.id`.

Consequences that shape KIE:

1. The `ChatResponder` protocol is the correct, already-existing seam. KIE can be added as a second
   responder without touching the deterministic one.
2. There is **no training API and no job runner in the backend**. PATRON training lives in the
   separate `PATROR/` project (CLI only). "Start authorized training jobs" therefore needs new,
   explicitly gated infrastructure — it cannot be a thin wrapper today.
3. The backend has no authentication (loopback-only, single user) and binds 127.0.0.1. Tool
   authorisation must be an in-process policy, not a network trust boundary.

---

## 2. Where KIE plugs in (five seams)

| Seam | File | Change shape |
|---|---|---|
| Assistant | `app/chat/service.py` | Add `KieResponder` implementing `ChatResponder`; keep the rules responder as fallback when the model is unloaded/unavailable. |
| Composition | `app/container.py` | Build a `KieService` (model manager + tool engine) once, inject into `ChatService`; expose on `AppContainer`. |
| HTTP | `app/api/v1/kie.py` (new) + `router.py` | New `/kie/*` namespace. Existing `/chat/*` responses unchanged. |
| Streaming | `app/api/ws.py` sibling `app/api/kie_ws.py` (new) | Push token deltas + tool events. Existing `/ws/market` untouched. |
| UI | `apps/desktop/src/pages/ChatPage.tsx` | Same page, same design tokens; add stream consumption, mode switch, tool trace accordion. |

Hard rule: `/chat/*` request/response schemas stay byte-compatible. KIE is additive.

---

## 3. Runtime decision

### 3.1 What was verified on this machine

| Check | Result |
|---|---|
| `C:\Windows\System32\vulkan-1.dll` | present (AMD driver Vulkan loader) |
| huggingface.co reachability | HTTP 200 |
| Free disk on `C:` | 161 GB |
| Backend Python | 3.12.10, `backend/.venv` with torch 2.4.1+cpu, fastapi 0.163, numpy 2.5.5, psutil 7.2.2 |
| MSVC / `cl.exe` | **absent** |
| `cmake`, `ninja`, `glslc` (Vulkan SDK) | **absent** |

The missing toolchain is the single most important constraint: it rules out the usual
`pip install llama-cpp-python` with `-DGGML_VULKAN=ON` source build, and it means a from-source
llama.cpp build needs a multi-GB Visual Studio Build Tools + Vulkan SDK install (admin, elevated).

### 3.2 Chosen runtime

**In-process llama.cpp GGUF inference via the official prebuilt Vulkan dynamic libraries, bound
with a thin `ctypes` shim.**

- Download the pinned `llama-b####-bin-win-vulkan-x64.zip` release, keep only
  `llama.dll`, `ggml.dll`, `ggml-base.dll`, `ggml-cpu.dll`, `ggml-vulkan.dll` under
  `backend/models/kie/runtime/<tag>/`.
- `kie/runtime/bindings.py` declares only the C symbols KIE needs (~45 functions from `llama.h`
  plus the sampler API), loads them with `ctypes.CDLL`, and is the *only* file allowed to touch
  `ctypes`. Everything above it is plain Python.
- Same shim works unchanged with the CPU build (`bin-win-cpu-x64`) → CPU fallback is a config
  switch plus a different DLL directory, not a second code path.
- Pin the release tag in `backend/config/kie.yaml` and record it in the manifest; llama.cpp's C ABI
  is not stable across releases, so silent upgrades are forbidden.

### 3.3 Options considered and rejected

| Option | Verdict |
|---|---|
| Ollama | Explicitly forbidden. |
| `llama-server.exe` subprocess + HTTP | It is an external model-serving application; also duplicates the API surface and adds a port. Rejected. The DLL is the same compute engine, embedded. |
| `llama-cpp-python` | Needs MSVC + CMake for Vulkan; prebuilt wheels are CPU-only. Kept as a documented fallback only if the ctypes shim proves unworkable. |
| Transformers + PyTorch (4B BF16) | ~8 GB weights, no Vulkan path in torch on Windows/ROCm-unsupported Polaris, far slower. Only usable as a reference oracle for tokenizer/template parity tests. |
| Cloud API | Forbidden. |

### 3.4 Model artifact

- `Qwen/Qwen3-4B-GGUF`, Q4_K_M (≈2.5 GB) as the default; Q5_K_M (≈2.9 GB) as a quality option
  that still fits the 8 GB budget with 8k context.
- License: Apache-2.0. Ship `LICENSE`, model `NOTICE`/model card link, and a
  `THIRD_PARTY_NOTICES.md` entry. Local weights live under `backend/models/kie/` (git-ignored);
  the repo stores only the manifest, hashes and download script.
- Tokenizer + chat template come from the GGUF metadata: `llama_model_chat_template` and
  `llama_chat_apply_template`. KIE never hand-writes ChatML unless the template is missing —
  and then it fails loudly rather than guessing.
- Qwen3 is hybrid-thinking. `enable_thinking=false` for **fast** mode, `true` for **reasoning**
  mode; the template kwarg is passed through the same `llama_chat_apply_template` call.

---

## 4. Package layout

New package `backend/app/kie/` (import root is `backend/`, so it is `app.kie.*`, consistent with
every other backend module). One directory per brief-mandated module, each with an explicit
interface module and no cross-imports except through `kie/contracts.py`.

```text
backend/app/kie/
  contracts.py        # dataclasses + Protocols only: Message, ToolSpec, ToolCall, ToolResult,
                      # ModelInfo, GenerationStats, KieEvent, EnginePort, ToolPort, ...
  core.py             # KIE Core: request lifecycle, mode routing, event fan-out, cancellation
  model_manager.py    # load/unload, layer offload, VRAM/RAM budget, health, warmup, single-flight
  runtime/
    bindings.py       # ctypes declarations (only file that may use ctypes)
    llama.py          # EnginePort impl: context, batched decode, sampler chain, streaming callback
    template.py       # chat-template + tool-schema rendering/parsing/validation
  reasoning.py        # Reasoning Engine: thinking-mode control, plan text, budget limits
  planner.py          # Planner: decompose goal → ordered steps (tool or answer)
  tools/
    registry.py       # ToolSpec registration, JSON-schema validation, authorisation levels
    engine.py         # Tool Engine: dispatch, timeout, retry, result truncation, audit
    kbmti_patron.py   # PATRON tools (read-only)
    kbmti_market.py   # market data tools (read-only)
    kbmti_system.py   # system/monitor tools (read-only)
    kbmti_training.py # Phase E only: authorized job control (see §11)
  workflow.py         # Workflow Controller: step state machine, loop guard, budgets
  memory.py           # Memory: conversation recall + market-fact cache over SQLite (no new deps)
  analysis.py         # Analysis Engine: deterministic derivations over tool output (no LLM)
  validator.py        # Result Validator: independent verification of tool output + final claims
  service.py          # KieService facade used by container/HTTP/WS
```

`ModelManager` is a process singleton behind a lock: one loaded model, one active context, a small
queue. Two concurrent generations on 8 GB VRAM is not a goal and will not be attempted.

---

## 5. Request flows

**Fast mode** (default, tool-capable, no visible chain-of-thought):

```text
user text
  → core.build_prompt(mode=fast, tools=registry.specs(), context=market_snapshot)
  → template.render(Qwen3 tool-call format)
  → llama.decode_stream  ──token deltas──▶ WS event "token"
  → parse `<tool_call>{...}</tool_call>` blocks
  → tools.engine.execute(call) ──▶ "tool_call" / "tool_result" events
  → append tool result as `<tool_response>`, loop (max 4 iterations, max 2 retries per call)
  → final answer → validator.check() → persist → "done"
```

**Reasoning mode**: same, with `enable_thinking=true`; thinking spans are streamed as a separate
`"thinking"` event type and never persisted into the visible assistant message body.

**Degraded paths**

| Condition | Behaviour |
|---|---|
| Model not loaded | `/kie/*` returns `MODEL_NOT_LOADED`; `ChatService` falls back to `RuleBasedResponder`; UI badge shows "KIE offline — deterministic answers". |
| Model loading | Requests queue with a bounded timeout, `503`-style `MODEL_LOADING` with progress. |
| GPU init fails | `ModelManager` retries with `n_gpu_layers=0` on the CPU DLL build, emits one `fallback` event, marks `backend="cpu"` for the rest of the session. |
| Generation cancelled | Token loop checks a `threading.Event` each decode step; partial text is kept and marked `cancelled=true`. |
| Timeout | Hard wall clock per generation (default 120 s) and per tool call (default 20 s). |

---

## 6. Tool-calling contract

`ToolSpec`:

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str                  # "patron.status"
    description: str           # ≤ 200 chars, written for a 4B model
    parameters: dict[str, Any] # JSON Schema, draft-07 subset, additionalProperties=False
    access: Access             # READ | WRITE | PRIVILEGED
    scopes: tuple[str, ...]    # ("patron:read", "market:read", ...)
    timeout_s: float = 20.0
    max_result_chars: int = 4000
```

Rules enforced by `tools/registry.py`, not by the model:

1. **Schema validation** before execution (`jsonschema` is *not* a dependency — a 150-line
   validator covering the subset KIE emits is used, so no new package is required).
2. **Authorization**: the model may only call names present in the registry, with `access=READ`
   unless the session carries an explicit, per-call confirmation token issued by the UI.
3. **No shell, no arbitrary code, no network**: the tool layer exposes **only** Python callables
   bound to `AppContainer` services. There is no `subprocess` tool, ever.
4. **Loop guard**: max 4 tool iterations/turn, max 2 retries/call, identical `(name, args)` twice
   in a row → abort with an explanation.
5. **Audit**: every call recorded (`kie_tool_calls`: id, run_id, name, args_json, ok, error,
   duration_ms, confirmed_by). Truncated args in logs; full args in DB.
6. **Independent verification**: `validator.py` re-reads the source of truth for claims that matter
   (a PATRON metric quoted in prose must match `ForecastService`/`PatronInferenceService` output
   within tolerance); mismatch → the claim is dropped and the answer is flagged.

Tool results are always wrapped as data:
`<tool_response name="...">{json}</tool_response>` — never as instructions.

---

## 7. Initial KBMTI tool registry (v1, read-only)

All of these already exist as service methods; the tools are thin, typed adapters.

| Tool | Backing call | Notes |
|---|---|---|
| `patron.status` | `PatronInferenceService.status()` | state, model id, params, latency |
| `patron.checkpoint` | `PatronInferenceService.info()` / `health()` | path, sha256, shape checks |
| `forecast.latest` | `ForecastService.latest()` | quantiles, barrier probs, as_of |
| `forecast.history` | `ForecastService.history(limit)` | paginated |
| `forecast.evaluate` | `ForecastService.evaluate(limit_runs)` | realized-vs-predicted |
| `market.snapshot` | `MarketDataService.snapshot()` | bid/ask/spread/freshness |
| `market.candles` | `MarketDataService.candle_series(limit)` | validated, completed only |
| `market.validate` | `MarketDataService.status()` + candle sanity | gaps, stale flag, provider |
| `signals.current` | `SignalService.current()` | rule-based bias + evidence |
| `indicators.latest` | `IndicatorEngine` | RSI/MACD/EMA/ATR/BB |
| `system.monitor` | `SystemMonitor` | CPU/RAM/GPU(if exposed)/process |
| `diagnostics.logs` | `/diagnostics` backend | tail N lines, redacted |
| `training.compare_checkpoints` | **Phase E** | reads `PATROR/experiments/*/walk_forward.json`; read-only |
| `training.start` / `.stop` | **Phase E** | privileged, confirmation-gated, job runner required |

Everything above `training.compare_checkpoints` is v1. Training *control* is deliberately deferred:
it needs a job runner + process isolation + a promotion gate (never auto-replace production
checkpoints), and shipping it in the same increment as the runtime would be unsafe.

---

## 8. API and streaming contract

New namespace, existing one untouched:

```text
GET    /api/v1/kie/status            → model state, backend (vulkan|cpu), ctx, VRAM estimate
POST   /api/v1/kie/load              → load (idempotent), progress via WS
POST   /api/v1/kie/unload            → unload, free VRAM
GET    /api/v1/kie/models            → installed artifacts + manifest hashes
POST   /api/v1/kie/chat              → non-streaming completion (parity with /chat shape)
POST   /api/v1/kie/chat/stream       → SSE: token / thinking / tool_call / tool_result / error / done
POST   /api/v1/kie/cancel            → cancel active run by run_id
GET    /api/v1/kie/tools             → serialized registry (names, descriptions, schemas, access)
GET    /api/v1/kie/runs/{run_id}     → run + tool-call audit trail
WS     /ws/kie                       → same events as SSE, plus load progress
```

SSE is used for chat streaming (one request, one stream, works through the Tauri webview without
extra plumbing); the WebSocket exists for load/progress telemetry alongside the existing
`/ws/market` pattern.

Persistence (same SQLite file, additive migration in `app/persistence/db.py`):

- reuse `chat_conversations` / `chat_messages`; add `meta.kie_run_id` to assistant messages,
- new `kie_runs` (id, mode, backend, prompt_tokens, completion_tokens, ttft_ms, tok_per_s, cancelled),
- new `kie_tool_calls` (§6.5).

The existing `responder` field already distinguishes producers, so exported conversations stay
readable and nothing existing has to change.

---

## 9. Memory policy on 8 GB VRAM / 16 GB RAM

| Item | Budget |
|---|---|
| Qwen3-4B Q4_K_M weights | ≈ 2.5 GB |
| KV cache, 8k ctx, f16 | ≈ 1.0–1.3 GB |
| Compute buffers / Vulkan | ≈ 0.6–1.0 GB |
| Windows desktop + browser | ≈ 1.5 GB |
| PATRON torch resident (CPU) | ≈ 0.3 GB RAM |

`ModelManager` reserves a configurable `vram_budget_mb` (default 6000), estimates per-layer cost,
and picks `n_gpu_layers` to fit; the remainder runs on CPU (`GGML_VULKAN` + `ggml-cpu` hybrid is
native to llama.cpp). Runtime RSS/VRAM is polled and surfaced through `system.monitor`; exceeding a
hard ceiling triggers unload, not paging.

Context is 8192 tokens with a `keep_first_n` system prompt + rolling summarisation of evicted
turns stored in `kie_runs`. Full 32k context is not planned for this GPU.

---

## 10. Customization pipeline (gated)

- Base GGUF is never modified. Adapters live in `backend/models/kie/adapters/<name>/`
  (manifest = base hash + dataset hash + hyperparameters + eval report).
- Path: tool-calling SFT dataset (JSONL of `messages` with Qwen3 tool-call turns) built from
  **recorded KIE sessions** (audited `kie_tool_calls`), plus hand-written workflow traces.
- QLoRA on a 4B is not trainable on 8 GB VRAM in practice; training is expected to run on CPU
  (slow, small adapters) or an external machine. QLoRA *compatibility* is documented, not assumed.
- Hard gate: no fine-tuning starts before the Phase A/B baseline benchmark suite exists and is
  recorded in `reports/kie/baseline.json`. Promotion requires beating the base model on the same
  benchmark, and an adapter can never be activated automatically.

---

## 11. Safety and reliability controls

| Risk | Control |
|---|---|
| Arbitrary command execution | No shell/code tool exists; registry is a closed allow-list. |
| Destructive action | `Access.PRIVILEGED` requires a one-time token minted by the UI after an explicit confirm dialog; tokens expire in 60 s and are single-use. |
| Infinite loops | 4 tool iterations/turn, 2 retries/call, duplicate-call detector, wall-clock budget. |
| Runaway generation | Per-token cancellation flag + hard timeout + `n_predict` cap. |
| Hallucinated metrics | `validator.py` re-reads the authoritative service and rejects mismatched numbers. |
| Prompt injection from tool output | Tool results are framed as data, truncated, and never appended as system instructions; the system prompt is re-asserted each turn. |
| Production checkpoint mutation | KIE has no write path to `PATROR`/`backend/models/patron`; the training tool is read-only in v1 and promotion is always a human action. |
| Model/runtime tampering | `kie/models.json` pins SHA-256 of the GGUF, DLLs and runtime tag; mismatch → refuse to load. |
| Silent GPU failure | Backend identity (`vulkan`/`cpu`) is reported on every run and shown in the UI; a CPU fallback is never presented as GPU performance. |

---

## 12. Benchmarks (baseline first, evidence only)

`backend/scripts/kie_bench.py` → `reports/kie/baseline.json` + `.md`, run on the target machine
with the desktop idle and no PATRON training in progress.

| Metric | Method |
|---|---|
| Tokens/s (decode) | median of 5 runs, 256 generated tokens, temp 0 |
| Time to first token | median of 10 runs, 512-token prompt |
| Prompt ingestion | tok/s at 512 / 2048 / 8192 ctx |
| Tool-call latency | registry call → validated result, per tool, p50/p95 |
| Tool selection accuracy | 60-case labelled set (which tool + valid args), exact-match |
| Argument validity | % schema-valid on first attempt |
| Multi-step completion | 20 scripted 3-step tasks, success = correct tool sequence + correct final answer |
| Memory | peak RSS, VRAM (Vulkan heap usage via `ggml` log + `psutil`) |
| Fallback parity | same suite with `n_gpu_layers=0`, recorded separately |
| Cancellation | time from `/cancel` to idle |

No numbers are claimed in this document. The existing PATRON measurements in
`reports/PATRON_NEXT_GEN_REVIEW.md` were taken while a training batch was running and are not
reused here.

---

## 13. Phased delivery

| Phase | Deliverable | Exit gate |
|---|---|---|
| **A. Runtime bring-up** | downloader + manifest, `bindings.py`, `llama.py`, probe script | Qwen3-4B Q4_K_M loads, generates coherent text, Vulkan device actually used (backend identity + VRAM delta), tok/s/TTFT measured with and without GPU |
| **B. Core + ModelManager** — *shipped 2026-11-19* | `contracts.py`, `core.py`, `model_manager.py`, `reasoning.py`, `planner.py`, `workflow.py`, `tools/{registry,engine}.py`, `service.py`, `/kie/status\|load\|unload\|models\|chat\|chat/stream\|cancel\|tools\|runs`, persistence | streaming, cancellation, unload/reload, CPU fallback all exercised; `/chat/*` unchanged (existing tests green) — see `docs/KIE_PHASE_B_RESULTS.md` |
| **C. Tools v1** | registry, engine, audit, validator, PATRON/market/system tools | 60-case selection benchmark recorded; every call schema-validated and audited; no shell path exists |
| **D. Reasoning + Planner + Workflow** | modes, plan/step state machine, loop guard | 20 multi-step tasks completed; loop guard proven by an adversarial test |
| **E. UI + training control** | ChatPage streaming/mode/trace, `/kie/runs`, read-only training introspection, then gated job control | design unchanged on other pages; destructive actions require confirmation; promotion still manual |
| **F. Customization** | dataset builder, LoRA/QLoRA pipeline, adapter manifest + eval | baseline recorded, adapter beats base on the same suite, activation is manual |

Phase A is the go/no-go: if Vulkan compute on the RX 580 (Polaris) either fails or is slower than
the CPU build, the plan is to ship CPU-mode with an honest UI badge rather than claim GPU support.

---

## 14. Risks

1. **No MSVC/CMake/Vulkan SDK** — the prebuilt-DLL route avoids it; if the pinned release's ABI
   does not match the shim, the fallback is installing Build Tools + Vulkan SDK and building
   llama.cpp once, pinned and committed as a manifest, not rebuilt per environment.
2. **Polaris Vulkan maturity** — GCN4 lacks the modern features ggml-vulkan prefers; some ops may
   fall back to CPU or be slow. Must be measured, not assumed.
3. **4B tool-calling reliability** — Qwen3-4B is competent but not frontier; the registry is
   designed for constrained schemas, few tools per turn, and deterministic retries.
4. **ABI churn in llama.cpp** — pin the release; the shim is versioned alongside it.
5. **Long first load** (≈5–15 s from disk) — warm load at backend startup behind a flag, with
   progress events, not on first user message.
6. **Existing chat behaviour** — adding a model must not regress deterministic answers; rules stay
   reachable and are the fallback.

---

## 15. Decisions taken (assumptions to confirm later)

1. **Runtime**: prebuilt llama.cpp Vulkan DLLs + ctypes, in-process, CPU build as fallback.
2. **Artifact**: `Qwen/Qwen3-4B-GGUF` Q4_K_M default, Q5_K_M optional; 8k context.
3. **Placement**: `backend/app/kie/` (not a new top-level package), exposed through
   `AppContainer` and a new `/api/v1/kie` namespace.
4. **Compatibility**: `/api/v1/chat/*` and `/ws/market` remain unchanged; rules responder stays as
   fallback. PATRON (`PATROR/`, `PATRON/`, `backend/app/patron`) is not modified.
5. **First increment**: Phase A only — runtime + measurement, no UI, no tools.

---

## 16. Licensing and attribution

- Qwen3-4B — Apache-2.0, © Alibaba Cloud. Keep the license text, add an entry to
  `THIRD_PARTY_NOTICES.md`, link the model card in `docs/`, and never ship weights in git.
- llama.cpp — MIT; its DLL distribution requires its `LICENSE` alongside the binaries.
- Existing KBMTI notices are preserved; no existing dependency is removed.
