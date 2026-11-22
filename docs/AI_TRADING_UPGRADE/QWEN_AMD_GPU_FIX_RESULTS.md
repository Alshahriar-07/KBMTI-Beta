# Qwen Availability and AMD Vulkan GPU Fix — Results

Date: 2026-11-22  
Target machine: AMD Radeon RX 580 2048SP (8 GB), Intel Core i5-9400F, 16 GB RAM, Windows 11  
Status: **implemented and verified on the target GPU**

## 1. Root cause of “Qwen Unavailable”

The model, GGUF file and Vulkan runtime were healthy. The application never started the model.

Two defaults combined to produce the false “Unavailable” state:

1. `KieConfig.autoload` defaulted to `False`.
2. `KieService.startup()` returned immediately unless autoload was enabled, and no normal
   application path called `POST /api/v1/kie/load`.
3. The assistant page requested market intelligence, saw `KieService.ready == False`, and
   correctly returned `QwenStatus.UNAVAILABLE`.

The status API made the problem harder to see:

- `KIE /status.available` meant “the manifest, model file and a runtime file exist”.
- `state` was `unloaded` and `ready` was `false`.
- The UI therefore showed an unavailable model even though the artifacts were complete.

This was a lifecycle/wiring defect, not a missing model or a broken llama.cpp build.

Secondary defects fixed at the same time:

- Vulkan failure silently fell back to the CPU runtime and could still report an
  accelerated-capable service.
- `READY` meant “the loader returned”, not “the model can answer”.
- There was no `INITIALIZING`, `GPU_BACKEND_UNAVAILABLE`, `GPU_MEMORY_INSUFFICIENT` or
  `INFERENCE_FAILED` state.
- The frontend had no Qwen initialization/retry control and no direct view of KIE health.

## 2. Files changed

Backend runtime and lifecycle:

- `backend/app/kie/config.py`
  - application autoload defaults to `true`;
  - `auto`/`vulkan` select **Vulkan only**;
  - CPU is used only with the explicit `KBMTI_KIE_BACKEND=cpu`.
- `backend/app/kie/contracts.py`
  - added the required `HealthState` vocabulary.
- `backend/app/kie/errors.py`
  - added `GPU_BACKEND_UNAVAILABLE` and `INFERENCE_FAILED` API errors.
- `backend/app/kie/model_manager.py`
  - health-state machine;
  - Vulkan device and offload verification;
  - measured VRAM/layer accounting;
  - real readiness generation before `READY`;
  - inference failure tracking and GPU identity preservation across reload;
  - no implicit CPU fallback.
- `backend/app/kie/service.py`
  - background `ensure_loading()` lifecycle;
  - truthful `available` (inference-ready, not artifact-present);
  - health/model/GPU/runtime/VRAM/layer/context diagnostics;
  - private model paths removed from public status responses;
  - redacted errors and correct shutdown ordering.
- `backend/app/kie/runtime/llama.py`
  - GPU identity fallback when Vulkan discovery is not logged again after reload.
- `backend/app/kie/runtime/bindings.py`
  - optional backend device-name introspection and device report fields.

Trading intelligence integration:

- `backend/app/intelligence/contracts.py`
  - additive `QwenStatus.INITIALIZING`.
- `backend/app/intelligence/service.py`
  - starts Qwen lazily when Qwen narration is requested;
  - reports INITIALIZING/GPU unavailable/memory/inference errors from real KIE health;
  - does not cache an initializing response;
  - fixed `/assistant/status` returning a stringified model-metadata dict.

Frontend:

- `apps/desktop/src/lib/api.ts`
  - `kieStatus()` and `kieLoad()`.
- `apps/desktop/src/lib/types.ts`
  - typed KIE health/status contract.
- `apps/desktop/src/pages/AssistantPage.tsx`
  - polls real KIE health;
  - renders initialization/ready/unavailable states;
  - exposes a controlled Retry Qwen action;
  - refreshes intelligence after a successful load and on the INITIALIZING→READY
    transition.
- `apps/desktop/src/components/assistant/QwenRuntimePanel.tsx` (new)
  - Qwen Ready / AMD Vulkan GPU / model / runtime / GPU / layers / VRAM / context /
    init time / real failure reason.
- `apps/desktop/src/components/assistant/QwenRuntimePanel.test.tsx` (new)
  - verified, initializing and GPU-unavailable synchronization tests.

Tests and documentation:

- `backend/tests/test_kie_core.py`
- `backend/tests/test_kie_api.py`
- `backend/tests/test_kie_runtime_smoke.py`
- `backend/tests/test_market_intelligence.py`
- `backend/tests/kie_fakes.py`
- `backend/tests/conftest.py`
  - fast tests explicitly disable real-model autoload; only `-m kie_runtime` touches GPU.
- `README.md`, `docs/AI_TRADING_UPGRADE/README.md`
  - current KIE defaults and test counts.

No PATRON forecasting, strategy validation, risk policy or trade-planning logic was changed.

## 3. Runtime and backend implementation

- Runtime: official ggml-org llama.cpp **b12503**, Windows Vulkan x64 prebuilt archive,
  `GGML_VULKAN=ON`, pinned in `backend/models/kie/manifest.json`.
- Runtime reported by `llama_version()`: `1.0.0-dev`; pinned release tag: `b12503`.
- Inference remains embedded in the Python backend through `llama.dll` and the existing
  ctypes bindings.
- No Ollama, llama-server subprocess, cloud API, NVIDIA package, CUDA flag or CUDA library
  was introduced.
- Model: `Qwen3-4B-Q4_K_M.gguf`, 2,491,323,904 bytes, Apache-2.0.

Readiness is a strict gate. `READY` requires all of:

1. manifest/model artifact verified;
2. model loaded;
3. Vulkan backend plugin loaded with a GPU device present;
4. layers confirmed offloaded;
5. measured buffers within the configured budget;
6. a real generation on the loaded context produced at least one token.

The health vocabulary is:

`NOT_INITIALIZED`, `INITIALIZING`, `MODEL_NOT_FOUND`, `MODEL_LOAD_FAILED`,
`GPU_BACKEND_UNAVAILABLE`, `GPU_MEMORY_INSUFFICIENT`, `READY`, `INFERENCE_FAILED`,
`STOPPING`.

Normal launch starts Qwen once in a background thread. The assistant also calls the
idempotent `ensure_loading()` path, so availability no longer depends on a manual API
call. A failed initialization is not retried automatically on every market poll; the
frontend Retry button calls `POST /api/v1/kie/load`.

## 4. AMD GPU detection evidence

Real backend identity line from the running process:

```text
ggml_vulkan: 0 = AMD Radeon RX 580 2048SP (AMD proprietary driver) | uma: 0 | rebar: 0 | fp16: 0 | bf16: 0 | fp4: 0 | warp size: 64 | shared memory: 32768 | int dot: 0 | matrix cores: none
```

Detected and reported as:

- backend: `vulkan`
- `gpu_name`: `AMD Radeon RX 580 2048SP`
- `gpu_device_present`: `true`
- Vulkan runtime status: `0`
- `accelerated`: `true`

These values came from the runtime/API; none are synthesized UI strings.

## 5. GPU offloaded layers

- Requested `n_gpu_layers`: `99` (offload all).
- Runtime result: **37 / 37 layers on Vulkan**.
- Health/status reports `offloaded_layers=37`, `total_layers=37`.
- Qwen3-4B has 36 transformer layers plus the output layer. A zero-layer or missing-device
  result is rejected as `GPU_BACKEND_UNAVAILABLE`.

## 6. VRAM usage

llama.cpp buffer accounting from the real load:

| Buffer | Measured |
|---|---:|
| Vulkan model | 2,375.9 MB |
| Vulkan KV cache | 576.0 MB |
| Vulkan compute | 320.8 MB |
| **Vulkan total** | **3,272.7 MB** |
| Configured budget | 4,096 MB |
| `within_budget` | `true` |

Windows PDH also reported the process:

- dedicated GPU memory: **2,048.0 MB**
- shared GPU memory: **334.7–364.7 MB**
- stable across repeated inference

The two numbers are different measurement methods: llama.cpp accounts its model/KV/compute
buffers, while PDH reports the process’s WDDM dedicated/shared counters. The configured
4,096 MB budget intentionally leaves headroom on the 8 GB adapter and carries the measured
376 MB Vulkan residual. The adapter’s full physical capacity was not queried through an
API; 8 GB is the documented hardware specification.

## 7. Context configuration

- `n_ctx`: **4,096**
- `n_batch`: **512**
- `n_ubatch`: **512**
- CPU threads used by llama.cpp: **5** (i5-9400F, one core left for application work)
- KV cache: **576 MB**
- one model, one context, one inference at a time

The smaller context is deliberate. It keeps the verified load at 3,272.7 MB plus residual,
instead of spending the remaining headroom on a larger KV cache. No second model copy is
created during retry or reload.

## 8. Real inference test results

All outputs below came from the real Qwen3-4B GGUF on the AMD Vulkan backend.

Readiness smoke generation:

- 25 prompt tokens, 4 generated tokens, 0.375 s.

Direct embedded KIE requests:

| Request | Completion tokens | Total | Finish |
|---|---:|---:|---|
| “Reply with exactly: KBMTI GPU ONLINE” | 9 | 1,707 ms | stop |
| “Return only the word STABLE.” | 6 | 1,540 ms | stop |

API request through `POST /api/v1/kie/chat`:

- input: “Reply with exactly: API GPU READY”
- output: `API GPU READY`
- backend: `vulkan`
- 170 prompt tokens, 7 completion tokens, 1,546 ms, finish `stop`.

Unified assistant pipeline (`scripts/qwen_pipeline_smoke.py`):

- `ai_status.status`: `USED`
- model label: `Qwen3-4B-Q4_K_M.gguf (Q4_K_M) · llama.cpp b12503`
- latency: 43,226 ms
- validation: schema valid, 11 known evidence references, all numeric claims verified
- decision remained `NO_TRADE`
- PATRON assessment remained `CONFLICTING_EVIDENCE`
- 6 PATRON predicted candles in the response

Qwen did not change the deterministic decision, risk output or PATRON numbers.

## 9. Measured inference speed

Verified on this RX 580 / i5-9400F machine:

| Run | Prompt | Completion | TTFT | Total | Throughput |
|---|---:|---:|---:|---:|---:|
| Direct request 1 | 172 | 9 | 1,225 ms | 1,707 ms | 18.87 tok/s |
| Direct request 2 | 177 | 24 | 1,190 ms | 2,415 ms | 18.85 tok/s |
| Direct request 3 | 170 | 6 | 1,219 ms | 1,540 ms | 18.83 tok/s |
| API request | 170 | 7 | 1,176 ms | 1,546 ms | 18.87 tok/s |

Initialization time measured 2.846–3.327 s from load start to verified `READY`; reload was
3.187 s. The first model load measured 2.898 s before the smoke check.

## 10. Stability results

- Three consecutive real generations completed without a crash or context reset failure.
- PDH dedicated VRAM stayed flat at 2,048 MB across all three requests.
- Explicit unload returned `health_state=NOT_INITIALIZED`, `ready=false`.
- Reload returned `READY`, Vulkan, 37/37 layers and passed a new smoke generation.
- A post-reload generation returned `RELOADED` normally.
- The device name remained correct after reload.
- Background API startup reached `READY` with no manual load call.
- API chat and `/assistant/status` both reported Qwen ready and used.
- No private filesystem paths appeared in the checked `/kie/status` response.

## 11. Regression and safety tests

- Backend fast suite: **288 passed, 1 deselected, 1 warning**.
- Real runtime smoke: **1 passed** (`-m kie_runtime`).
- Ruff: clean across `app`, `tests`, `scripts` and `scripts/train_patron_candidate.py`.
- Frontend: **33 tests passed** (8 files).
- Frontend TypeScript: clean.
- Frontend ESLint: clean.
- Production build: succeeded, 654.29 kB main bundle; only the pre-existing chunk-size
  warning.

Coverage added for:

- missing model → `MODEL_NOT_FOUND`;
- corrupt/load failure → `MODEL_LOAD_FAILED`;
- Vulkan failure → `GPU_BACKEND_UNAVAILABLE` with no CPU attempt;
- GPU device absent → `GPU_BACKEND_UNAVAILABLE`;
- VRAM budget failure → `GPU_MEMORY_INSUFFICIENT`;
- smoke generation failure → `INFERENCE_FAILED`, never `READY`;
- successful Vulkan load and inference;
- explicit CPU-only configuration;
- autoload/ensure-loading lifecycle;
- API health accuracy and no false `available`;
- frontend READY, INITIALIZING and GPU-unavailable synchronization;
- existing malformed Qwen output and deterministic trading safety tests.

Commands used:

```bash
cd backend
PYTHONPATH=. .venv/Scripts/python.exe -m pytest -o addopts="-m 'not kie_runtime'" -q
PYTHONPATH=. .venv/Scripts/python.exe -m pytest -m kie_runtime tests/test_kie_runtime_smoke.py -q -o addopts=""
.venv/Scripts/python.exe -m ruff check app tests scripts ../scripts/train_patron_candidate.py

cd ../apps/desktop
npm run typecheck
npm run lint
npm run test -- --run
npm run build
```

## 12. Remaining limitations

- Per-engine GPU utilization percentage during decode was not sampled. The verified
  evidence is full 37/37 layer offload, the adapter identity, Vulkan buffer allocation,
  flat dedicated VRAM and repeatable GPU-backed inference/throughput.
- PDH reports 2,048 MB dedicated while llama.cpp accounts 3,272.7 MB of buffers; they are
  different counters, not interchangeable totals.
- Total physical VRAM is taken from the hardware specification; no DXGI/WMI capacity query
  was added.
- 4,096 context is the verified configuration. Larger contexts were not retested in this
  change.
- Vulkan device discovery is process-global and does not re-emit its name on reload; the
  manager preserves the first verified identity for the process lifetime.
- Qwen can hallucinate in unrestricted chat when asked about facts not supplied in the
  prompt (one exploratory hardware question produced an incorrect NVIDIA answer). It is
  not used as a hardware diagnostic, and the trading path validates schema, evidence refs
  and every numeric claim before accepting an answer.
- The production assistant uses a 4,096-token context and single-flight queue. Concurrent
  model copies and parallel generations are intentionally unsupported.

## 13. Exact instructions to run

Desktop (normal):

```bash
cd backend
.venv/Scripts/python.exe -m kbmti --mode production
```

Backend only:

```bash
cd backend
PYTHONPATH=. .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8756
```

Open the Visual AI trading assistant. The Qwen local inference panel shows
`Initializing Qwen…`, then `Qwen Ready` with `AMD Vulkan GPU`, the model, runtime,
GPU name, 37/37 layers, measured VRAM, context and initialization time. If startup fails,
the panel shows the actual health state and a Retry Qwen button.

Health check:

```bash
curl http://127.0.0.1:8756/api/v1/kie/status
```

Relevant defaults:

```text
KBMTI_KIE_ENABLED=true
KBMTI_KIE_AUTOLOAD=true
KBMTI_KIE_BACKEND=auto        # auto/vulkan require Vulkan; cpu is explicit
KBMTI_KIE_CTX=4096
KBMTI_KIE_VRAM_BUDGET_MB=4096
KBMTI_KIE_GPU_LAYERS=99
```

If the pinned artifacts are missing, install them with the existing script:

```bash
cd backend
.venv/Scripts/python.exe scripts/kie_fetch_runtime.py
```

## Acceptance summary

| Criterion | Result |
|---|---|
| Qwen no longer incorrectly reports Unavailable | Verified |
| Underlying loading/lifecycle issue fixed | Verified |
| Qwen3-4B loads successfully | Verified |
| AMD RX 580 2048SP detected by Vulkan | Verified |
| Inference confirmed on AMD GPU | Verified (37/37 layers, Vulkan buffers, real generations) |
| No CUDA dependency | Verified |
| No Ollama/external inference server introduced | Verified |
| No silent CPU fallback | Verified; GPU failure is `GPU_BACKEND_UNAVAILABLE` |
| Existing KBMTI functionality and safety rules intact | Verified by 288 backend + 33 frontend tests |
