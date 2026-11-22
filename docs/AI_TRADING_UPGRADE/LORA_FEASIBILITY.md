# LoRA feasibility on the target workstation

**Date:** 2026-11-22
**Decision:** **Local LoRA training is not feasible with the verified environment.** No
adapter was trained and no training result is claimed. The model registry and approval
workflow are implemented so a future, separately approved environment can register a
candidate without changing production weights.

## Measured environment

Commands actually run from `backend/`:

```powershell
python -c "import platform, psutil; ..."
powershell.exe -NoProfile -Command "Get-CimInstance Win32_VideoController | ..."
python -c "import torch; ..."
```

| Fact | Measured value |
|---|---|
| OS | Windows 11 (10.0.26300) |
| CPU | Intel64 Family 6 Model 158, 6 cores / 6 threads (i5-9400F class) |
| RAM | 15.92 GB |
| GPU | AMD Radeon RX 580 2048SP, 8 GB class, driver 31.0.21925.1001 |
| PyTorch | 2.4.1+cpu |
| CUDA available | `False` |
| Inference runtime | Existing embedded llama.cpp + Vulkan; unchanged |

## Why local training is not feasible

1. **No supported training backend.** The existing RX 580 path is Vulkan inference via
   llama.cpp. That does not provide PyTorch autograd or LoRA training. The installed
   PyTorch is CPU-only; `torch.cuda.is_available()` is false.
2. **ROCm is not a supported Windows path for this GPU.** The RX 580 is a GCN4-era card;
   ROCm's supported Windows stack does not cover it. Installing an unofficial build
   would be an unapproved, unverified environment change.
3. **CPU QLoRA is not practical on 16 GB RAM.** A 4B model at 4-bit still requires the
   quantized weights plus dequantization workspaces, activations, gradients and optimizer
   state. Even if a small batch/sequence fit, throughput on six CPU cores would make a
   useful dataset run unreasonably long, and peak RAM would risk swapping. This is an
   estimate from the measured hardware, not a benchmark of a training run.
4. **Inference availability must be preserved.** Training inside the inference process
   is forbidden. The model is ~2.4 GB and competes for the same memory budget; a local
   training job would make the production assistant unavailable.

## What would be required

A separate, explicitly approved environment with a supported training GPU (or a rented
GPU), a pinned base-model hash, a reviewed dataset manifest, and an isolated process.
The candidate would be evaluated against the base+RAG+tools champion on held-out
structured tasks before any promotion. Promotion still requires an operator action and
one-step rollback.

## Implemented controls

- `training_jobs` records a requested dataset, requester, approval state and config.
- A job moves from `AWAITING_APPROVAL` to `APPROVED_NOT_RUN`; approval does **not**
  start training.
- `model_versions` stores candidates with `CANDIDATE` status. Only an explicit
  `promote` call with an actor activates one; the previous champion is marked inactive
  and recorded as the rollback target.
- Production Qwen weights, PATRON weights and the inference runtime are untouched.

## Evidence boundary

This document reports hardware facts and a reasoned decision. It does **not** report a
LoRA loss curve, adapter quality, speedup or model improvement, because no training was
run.
