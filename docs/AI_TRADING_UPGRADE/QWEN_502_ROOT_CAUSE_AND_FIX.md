# Qwen HTTP 502 — root cause, fix and verification

**Date:** 2026-11-23
**Status:** **resolved for the reproduced failure**
**Runtime:** Qwen3-4B Q4_K_M, embedded llama.cpp b12503, AMD Radeon RX 580 2048SP, Vulkan
**Backend:** `http://127.0.0.1:8756`
**Frontend path:** Vite dev/preview proxy at `http://127.0.0.1:5173`

## 1. Executive summary

The 502 was **not** a timeout, schema error or normal Qwen inference failure. The
backend process **aborted during Qwen initialization** with:

```text
OMP: Error #15: Initializing libomp.dll, but found libiomp5md.dll already initialized.
```

PyTorch (loaded first by PATRON) loads Intel OpenMP (`libiomp5md.dll`); the pinned
llama.cpp Vulkan runtime loads LLVM OpenMP (`libomp.dll`). LLVM's runtime treats the
second runtime as fatal and calls abort. Python cannot catch that, so the HTTP
connection disappears and the Vite proxy returns **502 Bad Gateway** with an empty
body.

The fix enables the documented Windows duplicate-OpenMP guard before either runtime
initializes, while preserving the Vulkan backend and the existing readiness gate.
The same cold-start request through the previous 502 path now returns **HTTP 200**
with a validated Qwen result on `AMD Radeon RX 580 2048SP`, 37/37 layers.

## 2. Exact reproduction

### Before the fix

1. Start the backend without `KMP_DUPLICATE_LIB_OK`:

   ```bash
   cd backend
   env -u KMP_DUPLICATE_LIB_OK PYTHONPATH=. .venv/Scripts/python.exe -m app
   ```

2. Start the frontend proxy:

   ```bash
   cd apps/desktop
   npm run dev -- --host 127.0.0.1
   ```

3. Request the unified endpoint through the proxy:

   ```bash
   curl -i \
     'http://127.0.0.1:5173/api/v1/assistant/market-intelligence?use_qwen=true&refresh=true'
   ```

**Observed:** `HTTP/1.1 502 Bad Gateway`, empty body, `Content-Type: text/plain`.
The backend log ended after PATRON load with the `OMP: Error #15` line. The backend
process no longer existed; `curl` to `127.0.0.1:8756` returned connection refused.

### Request lifecycle boundary

| Stage | Before |
|---|---|
| Frontend fetch | request sent |
| Vite proxy | forwarded to 8756 |
| `/assistant/market-intelligence` | accepted |
| Intelligence pipeline | deterministic analysis built |
| Qwen service | `startup()` / `ensure_loading()` started |
| PATRON / PyTorch | loaded `libiomp5md.dll` |
| Model manager / llama.cpp | loaded `libomp.dll`; **native abort** |
| API response | never written |
| Vite proxy | upstream socket closed → **502** |

The failing boundary is the **native runtime initialization inside the backend**,
not the HTTP handler. No Python exception handler or timeout can catch it.

## 3. Evidence

### Original failing run

```text
20:15:58  backend ready
20:16:01  PATRON loaded (2607 ms)
          OMP: Error #15: Initializing libomp.dll, but found libiomp5md.dll already initialized.
          [process exits]
```

Direct request after the abort:

```text
curl: (7) Failed to connect to 127.0.0.1:8756
```

Through the proxy:

```text
HTTP/1.1 502 Bad Gateway
Vary: Origin
Content-Type: text/plain
Content-Length: 0
```

### Why it was not the previous AMD/Vulkan issue

- The Vulkan artifacts are present and the identity line names the RX 580.
- The process dies **before** a Vulkan model-load failure can be reported.
- With the compatibility guard, the same artifacts load, report `backend=vulkan`,
  `gpu_name=AMD Radeon RX 580 2048SP`, `offloaded_layers=37`, `total_layers=37`.
- No CPU, Ollama or cloud fallback is attempted or reported.

### Why it was not a timeout

- The 502 arrived immediately after the process disappeared, not after a configured
  request timeout.
- `KieConfig.generation_timeout_seconds` is 120 s; the failing request never reached
  a generation.
- The Vite proxy has no shorter application timeout in this path.

## 4. Fix

### 4.1 Native coexistence guard

New module: `backend/app/kie/runtime/openmp_compat.py`.

- Windows-only.
- Sets `KMP_DUPLICATE_LIB_OK=TRUE` if the operator has not already set it.
- Called by `create_app` **before** the lifespan starts KIE, but only when both
  `patron_enabled` and `container.kie.enabled` are true.
- Logs a warning that this is an OpenMP compatibility mode, not a backend change.
- Does not change model selection, offload, memory budget, queue, validation,
  strategy, risk, planning or execution.

This is the documented LLVM/Intel OpenMP coexistence guard. It is required because
the application intentionally keeps two independently packaged native runtimes in
one process. The real-runtime test below proves the pair can load and generate; the
guard is not a substitute for the readiness smoke test.

### 4.2 Correlation IDs and error envelopes

`backend/app/main.py` now:

- accepts a safe `X-Request-ID` (1–64 chars) or mints a UUID;
- returns it on every HTTP response;
- logs method, path, status, duration and request ID without query strings or
  credentials;
- includes `request_id` in `ApiError`, validation and unexpected-error JSON;
- maps unexpected exceptions to `500 INTERNAL_ERROR` instead of leaking a traceback
  or a fake success;
- keeps the existing 413/422/503 envelopes.

### 4.3 Explicit Qwen states

`backend/app/intelligence/service.py` and `contracts.py` now:

- add `INITIALIZATION_TIMEOUT`;
- keep `INITIALIZING` while the bounded readiness wait is still in progress;
- return `INITIALIZATION_TIMEOUT` with the waited seconds when that budget expires;
- inspect the KIE `finish`/`cancelled` fields and map `finish=timeout` to
  `QwenStatus.TIMEOUT` without parsing partial text;
- never cache `INITIALIZING` or `INITIALIZATION_TIMEOUT`, so a later ready state can
  be picked up;
- preserve the deterministic analysis and mark `ai_status.used=false` on every
  failure;
- never fabricate a Qwen answer.

### 4.4 Single-flight and cache behavior

- The backend already held `_market_lock` around inference; it now also returns a
  result completed by a concurrent request when that result is newer than the
  request's own start time. A duplicate refresh therefore cannot launch a second GPU
  generation.
- The existing 45 s cache is keyed by snapshot, evaluation, plan, forecast run and
  `use_qwen`, so components and polls share one inference.
- The frontend disables the analysis retry while a request is in flight and uses a
  single explicit retry action.

### 4.5 Frontend behavior

`apps/desktop/src/lib/api.ts`, `usePolling.ts`, `AssistantPage.tsx` and
`AiIntelligencePanel.tsx` now:

- preserve the HTTP status, machine code and correlation ID in `ApiError`;
- map 502/504 to a retryable `UPSTREAM_UNAVAILABLE` message that says the last
  successful analysis is preserved;
- show the correlation ID in the error banner;
- offer **Retry analysis** only when the error is retryable and not already loading;
- keep previous successful data instead of blanking the workspace;
- distinguish `INITIALIZING`, `INITIALIZATION_TIMEOUT`, `TIMEOUT`, `INVALID`,
  `UNAVAILABLE` and `USED` in the AI status/readiness UI;
- keep the Qwen runtime panel polling actual `READY`/`INITIALIZING`/failure state.

No fake AI output is rendered after a failure.

## 5. Before / after

| Check | Before | After |
|---|---|---|
| Backend survives PATRON + Qwen load | **no (OMP abort)** | **yes** |
| Vite unified request | **502, empty body** | **200, validated JSON** |
| Qwen backend | not reached | `vulkan` |
| GPU | not reached | `AMD Radeon RX 580 2048SP` |
| Offload | not reached | 37/37 layers |
| Cold start Qwen ready | process died | ~4.4 s (observed 20:38:46.860) |
| Unified inference | none | 47.2–50.9 s |
| Cache read | none | 0.9 s, same `run_id` |
| Correlation ID | none | `X-Request-ID` returned and logged |
| On Qwen timeout | process/connection loss risk | explicit `TIMEOUT`, deterministic response |
| On initialization timeout | indefinite state | explicit `INITIALIZATION_TIMEOUT` |
| On malformed output | failure | `INVALID`, deterministic response |

## 6. API examples

Success (abridged):

```http
HTTP/1.1 200 OK
X-Request-ID: qwen-502-coldstart-20261123
Content-Type: application/json
```

```json
{
  "decision": "NO_TRADE",
  "execution": "DISABLED",
  "ai_status": {
    "used": true,
    "status": "USED",
    "model": "Qwen3-4B-Q4_K_M.gguf (Q4_K_M) · llama.cpp b12503",
    "run_id": "df1af9c53ad54e2fa6ccb7def32cca4e",
    "latency_ms": 47241.64,
    "validation_notes": ["schema valid", "11 known evidence references", "all numeric claims verified"]
  },
  "readiness": {
    "qwen": {"status": "READY", "reason_code": "USED"},
    "strategy": {"status": "PENDING"}
  }
}
```

Initialization timeout (deterministic body remains valid):

```json
{
  "ai_status": {
    "used": false,
    "status": "INITIALIZATION_TIMEOUT",
    "error": "Qwen did not finish initializing within 25.0s. It remains on the AMD Vulkan runtime; deterministic interpretation returned..."
  },
  "readiness": {"qwen": {"status": "FAILED", "reason_code": "INITIALIZATION_TIMEOUT"}},
  "execution": "DISABLED"
}
```

Inference timeout:

```json
{
  "ai_status": {
    "used": false,
    "status": "TIMEOUT",
    "error": "Qwen inference reached its configured processing limit (120.0s); deterministic interpretation returned. Run id: ..."
  },
  "execution": "DISABLED"
}
```

Error envelope:

```json
{
  "error": {
    "code": "MODEL_LOAD_FAILED",
    "message": "Qwen model failed to load.",
    "details": {},
    "request_id": "backend-request-2"
  }
}
```

A 502 that is genuinely generated by the proxy (backend actually down) is surfaced
by the frontend as a retryable `UPSTREAM_UNAVAILABLE` with the last successful
analysis preserved. It is not converted to a fake AI success.

## 7. Verification

### Backend

```text
305 passed, 2 deselected, 1 warning in 77.69s
```

The 2 deselected are the opt-in real-runtime suites. Ruff:

```text
All checks passed!
```

### Frontend

```text
typecheck  passed
lint       passed (0 warnings)
tests      37 passed (10 files)
build      passed
```

### Real GPU integration (not mocked)

`backend/tests/test_patron_qwen_runtime.py` was run in a fresh process with no
`KMP_DUPLICATE_LIB_OK` pre-set:

```bash
cd backend
env -u KMP_DUPLICATE_LIB_OK PYTHONPATH=. .venv/Scripts/python.exe \
  -m pytest -m kie_runtime tests/test_patron_qwen_runtime.py -q
```

Result: **1 passed**. It imports PyTorch first, then loads the real pinned GGUF
through llama.dll on Vulkan, performs a generation, and exits without an OMP abort.

### End-to-end through the original failing path

- Cold start request through Vite: **200**, `X-Request-ID` echoed, `ai_status=USED`,
  `run_id=df1af9c5…`, 47.2 s, Qwen readiness `READY`, `waited_seconds=0.21`.
- Earlier cold start through Vite: **200**, `ai_status=USED`, 50.9 s.
- Warm cache: **200** in 0.9 s with the same `run_id`, no second inference.
- `execution=DISABLED`, `position_size=None`, strategy gate `PENDING` throughout.

## 8. Changed files

**Backend**

- `backend/app/kie/runtime/openmp_compat.py` (new)
- `backend/app/main.py` (compatibility call, request IDs, error mapping)
- `backend/app/intelligence/contracts.py` (`INITIALIZATION_TIMEOUT`)
- `backend/app/intelligence/service.py` (explicit timeout states, finish handling,
  concurrent-result sharing, cache exclusions)
- `backend/pyproject.toml` (stable first-party isort config)
- `backend/tests/test_openmp_compat.py` (new)
- `backend/tests/test_patron_qwen_runtime.py` (new, opt-in real GPU)
- `backend/tests/test_api.py` (correlation IDs)
- `backend/tests/test_market_intelligence.py` (timeout/concurrency coverage)

**Frontend**

- `apps/desktop/src/lib/api.ts`
- `apps/desktop/src/hooks/usePolling.ts`
- `apps/desktop/src/pages/AssistantPage.tsx`
- `apps/desktop/src/components/market/AiIntelligencePanel.tsx`
- `apps/desktop/src/lib/api.test.ts` (new)

**Documentation**

- this report
- `HUMAN_APPROVAL_WORKSPACE.md`
- `PATRON_RESEARCH_DECISION.md`
- `NEXT_RESEARCH_PRIORITIES.md`
- `PHASE_2_ACCEPTANCE_POLICY.md`
- `R-001_NO_SUPPORT_REFERENCE_SPEC.md`
- `R-002_ADVERSE_CHOCH_SPEC.md`
- README index updates

No production PATRON checkpoint, strategy rule, frozen threshold, Qwen Vulkan
selection, risk authority, position sizing, planning gate or execution setting was
changed by this fix.

## 9. Remaining limitations

- The guard is a **Windows-specific compatibility measure** for two independently
  packaged OpenMP runtimes. It is documented by LLVM as an unsupported workaround;
  the real-runtime test and repeated requests provide evidence for this environment,
  not a universal guarantee.
- Qwen inference is still ~47–51 s on this CPU/GPU and blocks one request thread.
  Other requests queue on the existing single-flight lock. No timeout was increased
  to hide this.
- If the backend process is genuinely down, the Vite proxy still returns a generic
  502. The UI now labels it as retryable and preserves prior data, but no proxy can
  return a backend JSON body when there is no backend.
- The real-runtime suite is opt-in (`-m kie_runtime`), so the default CI run does not
  load the 2.4 GB GGUF. That is intentional; the opt-in result is recorded above and
  is not represented as a mocked test.
- No long-duration soak test, multi-process stress test or driver-crash test was
  performed.

## 10. Resolution statement

**The reproduced Qwen 502 is fully resolved.** The original cold-start abort no
longer occurs; the exact proxy path returns 200 with a validated Qwen response on
the intended local AMD Vulkan runtime. Arbitrary 502s caused by a completely stopped
backend are partially mitigated at the UI (meaningful retryable error, preserved
state), but cannot be eliminated by application code when the upstream process is
absent.
