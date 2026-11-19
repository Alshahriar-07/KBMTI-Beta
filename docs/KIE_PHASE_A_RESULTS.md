# KIE — Phase A results

**Runtime bring-up and measurement (2026-11-19)**

Phase A of `docs/KIE_INTEGRATION_PLAN.md` was a go/no-go question: does the official prebuilt
llama.cpp Vulkan runtime load a Qwen3-4B GGUF **inside the KBMTI backend process** and produce
usable throughput on an AMD RX 580 (Polaris), or does the CPU build have to be the shipped path?

**Verdict: PASS.** The Vulkan runtime loads in-process, offloads 37/37 layers to the GPU, and is
**1.75× faster at token generation and ~3× faster at prompt processing** than the CPU build on the
same machine. It is not an order of magnitude: Polaris has no fp16, no cooperative-matrix and no
integer-dot support in this backend, and prompt processing is the weak point (3.0 s for a 525-token
prompt, ~12.4 s for 2 064 tokens). Both numbers are measured, not estimated, and the CPU build
remains a working fallback (10.96 tok/s decode).

Nothing from Phase B onward exists yet: no `KieCore`, no `/api/v1/kie` routes, no tools, no
streaming, no UI, no fine-tuning. `/api/v1/chat/*`, `ChatService` and everything under `PATRON/`
and `backend/app/patron/` are untouched.

---

## 1. Exit criteria (plan §13)

| Gate | Evidence | Result |
|---|---|---|
| Qwen3-4B Q4_K_M loads | 2.12 s to first `llama_model_load` return, 398 tensors, SHA-256 verified | PASS |
| Generates coherent text | §8, three finance/management answers, fast mode | PASS |
| Vulkan device actually used | Device line, `offloaded 37/37 layers to GPU`, `b12503-vulkan` DLL set, non-zero VRAM | PASS |
| VRAM delta measured | 0 → 2 048 MB dedicated (PDH) + 3 853 MiB of Vulkan buffers reported by llama.cpp | PASS (see §5) |
| tok/s and TTFT with and without GPU | §6, 5 decode reps × 256 tokens, 3 TTFT reps per prompt size | PASS |
| No Ollama / no `llama-server` subprocess / no external server | Single process; `llama-*‑impl.dll` (CLI/bench/server) deleted from both runtime folders | PASS |
| No source compilation | Prebuilt release zips only, extracted; no MSVC, no CMake, no Vulkan SDK | PASS |
| No PATRON / ChatService changes | Only `backend/app/kie/**`, `backend/scripts/kie_*.py`, `backend/tests/test_kie_runtime.py`, `backend/models/kie/**`, this document | PASS |

---

## 2. Runtime identity

| Item | Value |
|---|---|
| llama.cpp release | `b12503` (`https://github.com/ggml-org/llama.cpp/releases/tag/b12503`) |
| `llama_version()` | `1.0.0-dev` (the release tag is the identity that matters) |
| Vulkan archive | `llama-b12503-bin-win-vulkan-x64.zip`, SHA-256 `6c83027548f989a4d5c9502b31b580dc5e1254998bd49c1d78e85f316900d118` |
| CPU archive | `llama-b12503-bin-win-cpu-x64.zip`, SHA-256 `64bee9b6fece8e66c665c40290cbb84706af23c670041d024b56a71a39859d77` |
| Model | `Qwen/Qwen3-4B-GGUF` → `Qwen3-4B-Q4_K_M.gguf`, 2 497 280 256 bytes, SHA-256 `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` |
| Model license | Apache-2.0 (weights), llama.cpp MIT — both recorded in `backend/models/kie/manifest.json` |
| Extracted footprint | `backend/models/kie/runtime/b12503-vulkan` 77 MB, `b12503-cpu` 37 MB, model 2.4 GB |

Selected DLL hashes actually loaded (identical `llama.dll` in both variants, as expected for one
build tree):

| DLL | SHA-256 |
|---|---|
| `b12503-vulkan/llama.dll` | `9556435b91316e8f8b7ac6f012d32e7eb5f019c1e8b637f8f5a8156dfe67dbc7` |
| `b12503-vulkan/ggml-vulkan.dll` | `6c91d33589c15759592995da4baa1402c7045cbd87c753e05dd43a7088f6648b` |
| `b12503-vulkan/ggml.dll` | `3719f52b642eb88e80ce8ab0bb33ee2e77cd4c83adbeb09459e9c4a480ba3d3d` |
| `b12503-vulkan/ggml-base.dll` | `587dcd7f81f80724ee14ff14953bafea1346968f3f096f951d95e4fa26e572df` |
| `b12503-cpu/ggml-cpu-haswell.dll` | `35677b3ac32a03b6b48217066fd1d620b2640b3719fd21e6a7c161108fd4d8ee` |

**ABI transcription** — the ctypes structs were written by hand from `include/llama.h` at this tag
and are asserted against the library's own defaults at load time (`describe_abi()`), so an upgrade
that changes the layout fails loudly instead of corrupting memory:

| Struct | Size | Sanity check against defaults |
|---|---|---|
| `llama_model_params` | 80 B | `n_gpu_layers=-1`, `split_mode=1`, `load_mode=-1`, `lazy_mode=1` |
| `llama_context_params` | 176 B | `n_ctx=512`, `n_batch=2048`, `n_ubatch=512`, `n_threads=4`, `flash_attn_type=-1`, `type_k/type_v=1` |
| `llama_batch` | 56 B | 3 tokens with positions 5,6,7 and logits on the last one |
| `llama_sampler_chain_params` | 1 B | — |

---

## 3. How the runtime is loaded

One process, no child process, no socket:

```text
backend/app/kie/runtime/bindings.py    os.add_dll_directory(<abs runtime dir>)  →  CDLL("llama.dll")
                                       llama_backend_init()
                                       ggml_backend_load_all_from_path(<runtime dir>)
backend/app/kie/runtime/llama.py       llama_model_load_from_file  →  llama_init_from_sampler-less context
                                       llama_memory_clear → llama_decode (chunked by n_batch) → sample
```

Two findings worth keeping:

1. **`llama_backend_init()` does not discover the backend plugins** in this build. Without an
   explicit `ggml_backend_load_all_from_path()` the model silently falls back to CPU while
   `llama_supports_gpu_offload()` still returns true. KIE calls it explicitly and records
   `status=0`, `device_count`, `gpu_device_present` per load.
2. **`llama_supports_gpu_offload()` is not trustworthy here.** The RPC backend registers itself as a
   GPU-type device, so a CPU-only plugin folder reports `true`. KIE derives its own flag from
   `ggml_backend_dev_by_type(GPU)` and keeps the raw llama value alongside it for transparency.

Loaded plugins (Vulkan run): RPC, Vulkan, CPU (`ggml-cpu-haswell.dll` — the correct variant for the
i5-9400F). Loaded plugins (CPU run): RPC, CPU only; `device_count=1`, no GPU device.

The CLI/bench/server implementation DLLs shipped in the archive (`llama-cli-impl.dll`,
`llama-bench-impl.dll`, `llama-server-impl.dll`, …) were deleted from both runtime folders: KIE never
needs them, and their absence removes any path to starting an external server.

---

## 4. GPU backend identity and offload verification

```
ggml_vulkan: 0 = AMD Radeon RX 580 2048SP (AMD proprietary driver) | uma: 0 | rebar: 0 |
                 fp16: 0 | bf16: 0 | fp4: 0 | warp size: 64 | shared memory: 32768 |
                 int dot: 0 | matrix cores: none
load_tensors: offloaded 37/37 layers to GPU
load_tensors:      Vulkan0 model buffer size =  2375.91 MiB
load_tensors:   CPU_Mapped model buffer size =   304.28 MiB
llama_kv_cache:    Vulkan0 KV buffer size =  1152.00 MiB
sched_reserve:    Vulkan0 compute buffer size =   324.77 MiB
sched_reserve: Vulkan_Host compute buffer size =    28.02 MiB
```

`37/37` is 36 transformer layers plus the output layer. The CPU build reports `offloaded 0/37` for
the same model, so the two runs differ only in placement.

The capability flags are the whole story of the performance below: **no fp16, no bf16, no
cooperative matrices, no integer dot product, no resizable BAR.** Every matmul therefore runs in
fp32 shaders on a 2017 architecture — which is why Vulkan helps here but does not transform the
machine.

---

## 5. Memory

| State | RSS (Vulkan) | RSS (CPU) | Process dedicated VRAM (PDH) | Process shared (PDH) |
|---|---|---|---|---|
| Before load | 119.6 MB | 120.5 MB | 0 MB | 0 MB |
| After load (ctx 8192) | 2 910.7 MB | 4 694.5 MB | 2 048.0 MB | 335.5 MB |
| During 256-token decode (peak) | 2 963.1 MB | 5 464.8 MB | 2 048.0 MB | ~336 MB |
| After unload | 495.7 MB | 127.6 MB | 6.3 MB | — |

**Why the VRAM number needs a caveat.** Windows PDH reports 2 048.0 MB dedicated for this process,
which is *less* than the 2 375.91 MiB model buffer llama.cpp itself allocated — the counter saturates
on this driver. It was probed with different offload depths:

| `n_gpu_layers` | PDH process dedicated |
|---|---|
| 12 | 1 360.2 MB |
| 24 | 2 048.0 MB |
| 99 (37/37) | 2 048.0 MB |

The counter moves up to ~2 GB and then clamps, so the authoritative footprint is llama.cpp's own
buffer accounting: **3 853 MiB (≈3.76 GiB) of Vulkan buffers** at 8 192 context — model 2 375.91 +
KV 1 152.00 + compute 324.77 + output 0.58 MiB — plus 304.28 MiB of CPU-mapped model data in RAM.
That leaves roughly 4 GiB free on the 8 GiB card, enough for one KIE context but not for two
concurrent 8k contexts (Phase B must treat `n_ctx` as the VRAM lever, not an afterthought).

The Vulkan RSS figure is not a leak: roughly 2.5 GB of the 2.9 GB is the memory-mapped GGUF the
driver copied to VRAM. Unload returns 6.3 MB of dedicated VRAM; the residual ~376 MB of RSS is the Vulkan
loader and driver bookkeeping, not model weights. The CPU build returns to 127.6 MB.

---

## 6. Benchmarks — CPU versus Vulkan

**Conditions.** Same process-local API, same model file, same context settings
(`n_ctx=8192`, `n_batch=512`, `n_ubatch=512`, `n_threads=5`), one backend per process, machine idle
(`competing_jobs: 0`, CPU load 5.2%/8.3%, 9.3 GB RAM free), each backend preceded by an 8-token
warm-up. Decode = 5 runs × 256 tokens at `temperature=0` after a short prompt; TTFT = 3 runs per
prompt size; values below are medians. Raw data: `backend/reports/kie/phase_a_vulkan.json`,
`phase_a_cpu.json`, `phase_a_both_20261119-110106.json`.

| Metric | Vulkan (37/37 layers) | CPU (0/37) | Speed-up |
|---|---|---|---|
| Model load, 8 192 ctx | 2.12 s | 2.16 s | — |
| Decode (256-token runs, median) | **19.21 tok/s** | **10.96 tok/s** | **1.75×** |
| Decode per-run spread | 19.19 – 19.21 | 10.94 – 10.98 | — |
| Prefill, 525-token prompt | 175.5 tok/s | 59.2 tok/s | 2.96× |
| TTFT, 525-token prompt | **3 020 ms** | 8 920 ms | 2.95× |
| Prefill, 2 064-token prompt | 167.2 tok/s | 48.9 tok/s | 3.42× |
| TTFT, 2 064-token prompt | 12 381 ms | 42 221 ms | 3.41× |
| Peak process VRAM | 2 048 MB (PDH; 3 853 MiB actual) | 0 | — |
| Peak RSS | 2 963 MB | 5 465 MB | — |

The three TTFT runs per prompt size are tight on both backends (Vulkan 3 001 / 3 032 / 3 020 ms and
12 347 / 12 381 / 12 383 ms; CPU 8 506 / 8 920 / 9 127 ms and 41 472 / 42 221 / 42 733 ms), and the
five decode reps are within 0.02 tok/s of each other, so these are real steady-state numbers rather
than a lucky run. An earlier pass with an unrelated training job busy on all six cores produced
CPU decode of 4.9 tok/s and prefill of 26 tok/s, while Vulkan prefill barely moved (180 tok/s) —
the GPU does not care about a busy CPU, the CPU backend very much does. **Never benchmark this box
while something else is training.**

**Interpretation.** Decode is memory-bandwidth bound: 2.4 GB of Q4_K_M weights per token against
~224 GB/s of GDDR5 on this card gives a hard ceiling near 93 tok/s, and the measured 19.2 tok/s is
≈21% of it — the rest is per-token dispatch and synchronisation overhead, which is exactly what
fp32-only shaders on Polaris cost. Prefill benefits more (3×) because a 512-token batch amortises
that overhead.

Raising the batch does not rescue prefill: with the same 2 064-token prompt, `n_batch`
256/1024/2048 gave 13.07 s / 11.91 s / 11.74 s. The 512 default was kept (a 10% gain does not pay
for the larger compute buffer).

Operationally: a typical KIE turn (system prompt + history ≈ 500 tokens) sees its first token after
**3.0 s on GPU, 8.9 s on CPU**, and then streams at 19.2 tok/s. At the full 8 192-token context,
prefill extrapolates to ~49 s (Vulkan) and ~169 s (CPU) — Phase B should cap the working context
well below that and keep the system prompt lean.

---

## 7. Reliability

| Test | Vulkan | CPU |
|---|---|---|
| 10 consecutive 32-token requests | RSS 2 963.1 → 2 963.0 MB, 19.21 → 19.21 tok/s | RSS 5 464.8 → 5 464.8 MB, 11.34 → 11.29 tok/s |
| Cancellation mid-generation (requested at 1.2 s) | 31.9 ms, `cancelled=True`, 20 tokens kept, context reusable immediately (follow-up request returns 16 tokens) | 0.3 ms, `cancelled=True`, 10 tokens kept, same guarantees |
| Unload then reload and generate | 2.00 s, 8 tokens, VRAM back to baseline first | 2.13 s, 8 tokens |
| Repeated load/unload cycles in one process | 3 cycles (12, 24, 99 layers) without leaking process state | — |
| FastAPI app built in the same process | `create_app(start_polling=False)` → 6 routes, title `KBMTI API` | same |

Memory is flat across runs (delta 0.0 / −0.1 MB) and throughput does not decay, which is the
property the "verify memory stability" criterion asks for. Cancellation is observed between decode
steps: llama.cpp's abort callback is CPU-only, so on Vulkan the latency is one token step
(~32 ms at 19 tok/s) — fast enough to feel instant, and the partial answer is kept.

Unloading is complete enough to re-load in ≈2 s, but Vulkan keeps ~376 MB of driver-side RSS after
unload. Phase B's `ModelManager` budget must count that residual instead of assuming a clean slate.

---

## 8. Coherence (fast mode, `temperature=0.2`, greedy-free)

System prompt: *"You are KIE, the local management-intelligence assistant of the KBMTI trading
system. Answer in at most three sentences. Never invent numbers."* Thinking disabled.

> **Q: A model's hit rate drops from 61% to 54% after a retrain. List the first two checks.**
> 1. Check if the model's performance decline is due to data drift or changes in the input
> distribution. 2. Verify if the retrain process was executed correctly and if the new data used for
> training is representative of the current environment. *(52 tokens, 19.4 tok/s)*

> **Q: Explain the difference between a data-quality warning and a trading signal.**
> A data-quality warning indicates potential issues with the reliability or accuracy of the data used
> in the system. A trading signal is a recommendation for investment decisions based on analyzed
> data. The two are distinct: one alerts to data problems, the other guides actionable decisions.
> *(55 tokens, 19.4 tok/s)*

> **Q: In one paragraph, explain what a volatility forecast is and how a desk should use it.**
> A volatility forecast is an estimate of the future range of price movements for an asset, typically
> measured by the volatility index. It helps desks anticipate potential market fluctuations and manage
> risk more effectively. By using volatility forecasts, a desk can adjust positions, set stop-loss
> limits, and allocate capital more efficiently… *(73 tokens, 19.4 tok/s)*

Text is coherent and on-topic; the model is unremarkable at arithmetic ("measured by the volatility
index" is hand-waving) which is precisely why KIE's tool layer, not the model, must supply numbers.

**Thinking mode** is on by default in Qwen3 and spends the output budget on reasoning: with
`thinking=True` the prompt *"Reply with exactly: KIE runtime online."* produced 40 tokens of visible
chain-of-thought and hit the cap without ever reaching the answer, where fast mode needed 9 tokens.
The GGUF template at this tag exposes no `enable_thinking` switch through
the C API, so fast mode appends the documented `/no_think` soft switch to the system prompt. That
works — reasoning collapses to an empty block — but the model still emits the block (7 tokens,
≈350 ms), which `LlamaRuntime` now strips from the returned text.

---

## 9. Measurement bugs found and fixed

These matter because each one would have produced a false claim in a report like this one.

1. **Async decoding inflated decode throughput by ~16×.** `llama_decode` returns after *enqueueing*
   on Vulkan; the GPU work happens later, inside the sampler's logits read. Summing per-step
   `llama_decode` times reported **306 tok/s** on a card whose memory bandwidth allows ~93. Fixed by
   timing wall clock between the first and last token and by calling `llama_synchronize()` after
   prefill. The same mistake made prefill appear ~10 000 tok/s at `n_batch ≥ prompt length`.
2. **VRAM counter saturation.** PDH `\GPU Process Memory\Dedicated Usage` clamps at 2 048 MB on this
   driver (proof in §5). Reported alongside llama.cpp's own buffer sizes rather than alone.
3. **`llama_supports_gpu_offload()` false positive** through the RPC backend, fixed as described in §3.
4. **PDH call crashed the interpreter** when the output pointer was declared as
   `POINTER(POINTER(PDH_FMT_COUNTERVALUE_ITEM_W))`; changed to `c_void_p` + `cast`.
5. **`llama_model_get_device` / `llama_model_n_devices` are C++-mangled** in this build and were
   removed from the bindings instead of being called by a guessed name.
6. **A relative `os.add_dll_directory` fails**; the runtime directory must be absolute.
7. **The KV cache is not cleared between requests** by llama.cpp: a second `generate()` on the same
   context returned `llama_decode failed with code -1`. `llama_memory_clear()` is now called at the
   start of every request.

---

## 10. Limitations and risks for Phase B

- **Prefill is the user-visible cost**, not decode. 3.0 s TTFT for a 525-token prompt is acceptable
  for a "thinking" assistant but not for chat; 8k context would be ~49 s. Cap `n_ctx` (4 096 is the
  honest default), keep the system prompt small, and stream a "reading context" state.
- **No fp16 / cooperative matrices / integer dot** on Polaris. There is no configuration flag that
  recovers this; it is the hardware generation. Do not promise GPU-class latency in the UI.
- **Real VRAM demand is 3.85 GiB at 8k context**, and PDH cannot be trusted to police it. The
  `ModelManager` budget must be computed from llama.cpp's buffer sizes (or a capability probe), not
  from the OS counter.
- **~376 MB of Vulkan driver RSS survives unload.** Budget it; do not assume a reload starts clean.
- **Thinking mode spends the whole output budget on reasoning** when left on (40 tokens without an
  answer versus 9 with fast mode). Fast mode is the default and must be
  visible in the UI badge, together with the backend identity (`vulkan`/`cpu`) — the plan requires
  that CPU fallback is never presented as GPU performance.
- **PDH is Windows-only**; the probe reports the limitation instead of inventing a number on other
  platforms.
- **One context, one request at a time** today: the runtime clears the KV cache per request, so
  Phase B needs an explicit single-flight queue rather than pretending concurrency exists.
- **Long-context behaviour is untested.** Phase A measured prefill up to 2 064 tokens; quality and
  memory at 8 192 are Phase B work.
- **Model runtime version is pinned to a moving dev stream** (`1.0.0-dev`, tag `b12503`). The
  manifest check exists so an upgrade is a deliberate act with a re-run of this benchmark.

---

## 11. Deviations from the plan

| Plan said | What was done | Why |
|---|---|---|
| Keep only `llama.dll`, `ggml.dll`, `ggml-base.dll`, `ggml-cpu.dll`, `ggml-vulkan.dll` | Keep the five plus the per-architecture `ggml-cpu-<arch>.dll` plugins, `ggml-rpc.dll`, `llama-common.dll`, `mtmd.dll`, `libomp.dll`; delete every `*-impl.dll` | b12503 splits the CPU backend into per-arch plugins; the loader picks `ggml-cpu-haswell.dll` on this CPU. The `-impl` DLLs are the CLI/bench/server implementations and are not needed. |
| Report VRAM from the OS | Report both PDH and llama.cpp buffer accounting | The OS counter saturates (§5) |
| Fast mode = no thinking | `/no_think` soft switch + empty-block stripping in the runtime | The C API at this tag has no `enable_thinking` |
| One probe script | Probe writes one JSON per backend and a combined envelope; `--backend both` runs each in its own process | ggml registers backends globally; loading two plugin sets in one process cross-links them, and a Vulkan driver fault would take the CPU numbers with it |

---

## 12. Reproduce

```bash
cd backend
# download + hash-verify runtime archives and the GGUF, write models/kie/manifest.json
PYTHONPATH=. .venv/Scripts/python.exe scripts/kie_fetch_runtime.py --backend both --check-model-hash

# full probe (Vulkan and CPU, separate processes), ~8 min on an idle machine
PYTHONPATH=. .venv/Scripts/python.exe -u scripts/kie_phase_a.py --backend both \
    --reps 5 --max-tokens 256 --ttft-runs 3 --stability-runs 10 --boot-api
#   → reports/kie/phase_a_vulkan.json, phase_a_cpu.json, phase_a_both_<stamp>.json

# regression guard for the shim (no model load, <1 s)
.venv/Scripts/python.exe -m pytest tests/test_kie_runtime.py -q
```

The machine must be idle (`host.competing_jobs` in the JSON must be empty) or the CPU numbers are
meaningless — see §6.
