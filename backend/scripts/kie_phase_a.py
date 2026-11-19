"""Phase A probe: validate the embedded llama.cpp runtime and benchmark Vulkan vs CPU.

Runs entirely inside one Python process (the same interpreter and venv the KBMTI backend
uses). It measures, and prints, only what it actually observed:

* runtime identity (llama.cpp tag/version, DLL set, struct sizes, backend devices),
* whether ggml's Vulkan backend initialised and how many layers were offloaded,
* VRAM before load / after load / peak during decoding / after unload,
* time-to-first-token, prompt ingestion and decode throughput,
* CPU-only vs Vulkan on identical prompts and sampling settings,
* load -> unload -> load cycles, repeated inference and memory stability,
* cancellation latency, and that the engine still works afterwards.

Usage (from ``backend/``):

    .venv/Scripts/python.exe scripts/kie_phase_a.py --backend both --reps 5

Artifacts: ``reports/kie/phase_a_<backend>.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import psutil  # noqa: E402

from app.kie.runtime.gpu_memory import GpuMemorySampler  # noqa: E402
from app.kie.runtime.llama import LlamaRuntime  # noqa: E402
from app.kie.runtime.manifest import load_manifest, resolve_model  # noqa: E402

PROBE_PROMPT = "Explain in one sentence what a calibrated volatility forecast is."


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def mem_snapshot(sampler: GpuMemorySampler, proc: psutil.Process) -> dict[str, object]:
    gpu = sampler.sample()
    return {
        "rss_mb": round(proc.memory_info().rss / (1024 * 1024), 1),
        "vram": gpu.as_dict(),
    }


class VramMonitor:
    """Polls process VRAM in the background and keeps the peak."""

    def __init__(self, sampler: GpuMemorySampler, interval: float = 0.1) -> None:
        self.sampler = sampler
        self.interval = interval
        self.peak_bytes: int | None = None
        self.samples = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> VramMonitor:
        self._thread = threading.Thread(target=self._run, name="kie-vram", daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.is_set():
            value = self.sampler.sample().process_dedicated_bytes
            if value is not None:
                self.samples += 1
                self.peak_bytes = value if self.peak_bytes is None else max(self.peak_bytes, value)
            self._stop.wait(self.interval)

    def __exit__(self, *_exc) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    @property
    def peak_mb(self) -> float | None:
        return None if self.peak_bytes is None else round(self.peak_bytes / (1024 * 1024), 1)


def build_prompt(rt: LlamaRuntime, target_tokens: int) -> str:
    """Grow a market-flavoured prompt until it tokenizes to at least ``target_tokens``."""
    filler = (
        "The PATRON network forecasts the next closed candle as quantiles with barrier probabilities. "
        "Validation covers the last three folds of the development split. "
    )
    text = "You are KIE, an embedded market intelligence assistant.\n\n"
    while rt.count_tokens(text) < target_tokens:
        text += filler
    return text


def parse_offload(lines: list[str]) -> dict[str, object]:
    """Extract the layers-offloaded evidence ggml prints at model load."""
    offload = [line for line in lines if "offloaded" in line.lower() or "offload" in line.lower()]
    buffer_lines = [line for line in lines if "buffer size" in line.lower()]
    gpu_total = None
    for line in lines:
        if "offloading" in line.lower() and "layers" in line.lower():
            gpu_total = line
    return {"offload_lines": offload, "buffer_lines": buffer_lines, "layer_line": gpu_total}


def bench_backend(name: str, args: argparse.Namespace, manifest, model_path: Path) -> dict[str, object]:
    proc = psutil.Process()
    sampler = GpuMemorySampler()
    variant = manifest.runtime(name)
    n_gpu_layers = args.gpu_layers if args.gpu_layers is not None else (99 if name == "vulkan" else 0)
    print(f"\n=== {name.upper()} backend | gpu_layers={n_gpu_layers} | dll={variant.path.name} ===")

    result: dict[str, object] = {
        "backend": name,
        "runtime_tag": variant.tag,
        "runtime_dir": str(variant.path),
        "requested_gpu_layers": n_gpu_layers,
        "started_at": now_iso(),
        "before_load": mem_snapshot(sampler, proc),
    }

    rt = LlamaRuntime(
        model_path,
        variant.path,
        n_gpu_layers=n_gpu_layers,
        n_ctx=args.ctx,
        n_threads=args.threads,
        n_batch=args.batch,
        n_ubatch=args.batch,
    )
    load = rt.load()
    result["abi"] = rt.abi()
    result["load"] = {
        "seconds": round(load.load_seconds, 2),
        "model": load.model,
        "context": load.context,
        "backend": load.backend,
        "warnings": load.warnings,
        "log": load.backend_log,
        "offload": parse_offload(load.backend_log),
    }
    result["after_load"] = mem_snapshot(sampler, proc)
    identity = rt.backend_identity()
    result["identity"] = {
        "llama_version": identity.get("llama_version"),
        "supports_gpu_offload": identity.get("supports_gpu_offload"),
        "backend_load": identity.get("backend_load"),
        "vulkan_devices": identity.get("vulkan_devices"),
    }
    print(f"  load {load.load_seconds:.2f}s | ctx {load.context.get('n_ctx')} | "
          f"vram after load {result['after_load']['vram']['process_dedicated_mb']} MB | "
          f"rss {result['after_load']['rss_mb']} MB")
    for line in identity.get("vulkan_devices") or []:
        print(f"  {line}")

    # -- warm up ------------------------------------------------------
    warm = rt.generate(prompt=PROBE_PROMPT, max_tokens=8, temperature=0.0)
    print(f"  warmup: {warm.generated_tokens} tokens, finish={warm.finish}")

    # -- time to first token / prompt ingestion -----------------------
    ttft_runs = []
    for target in (512, 2048):
        prompt = build_prompt(rt, target)
        runs = []
        for _ in range(args.ttft_runs):
            report = rt.generate(prompt=prompt, max_tokens=args.ttft_tokens, temperature=0.0)
            runs.append(
                {
                    "ttft_ms": round(report.ttft_ms, 2),
                    "prompt_tokens": report.prompt_tokens,
                    "prompt_tok_per_s": round(report.prompt_tok_per_s, 2),
                    "prompt_ms": round(report.prompt_ms, 2),
                }
            )
        summary = {
            "target_tokens": target,
            "prompt_tokens": runs[-1]["prompt_tokens"],
            "ttft_ms_median": round(statistics.median(r["ttft_ms"] for r in runs), 2),
            "prompt_tok_per_s_median": round(statistics.median(r["prompt_tok_per_s"] for r in runs), 2),
            "runs": runs,
        }
        ttft_runs.append(summary)
        print(f"  prompt {summary['prompt_tokens']} tok: TTFT {summary['ttft_ms_median']} ms, "
              f"ingest {summary['prompt_tok_per_s_median']} tok/s")
    result["ttft"] = ttft_runs

    # -- decode throughput -------------------------------------------
    decode_runs = []
    with VramMonitor(sampler) as monitor:
        for i in range(args.reps):
            report = rt.generate(prompt=PROBE_PROMPT, max_tokens=args.max_tokens, temperature=0.0)
            decode_runs.append(
                {
                    "run": i + 1,
                    "decode_tok_per_s": round(report.decode_tok_per_s, 2),
                    "ttft_ms": round(report.ttft_ms, 2),
                    "generated_tokens": report.generated_tokens,
                    "finish": report.finish,
                    "rss_mb": round(proc.memory_info().rss / (1024 * 1024), 1),
                    "vram_mb": sampler.sample().as_dict().get("process_dedicated_mb"),
                }
            )
            print(f"  decode run {i + 1}/{args.reps}: {report.decode_tok_per_s:.2f} tok/s "
                  f"(ttft {report.ttft_ms:.0f} ms)")
    decode_tps = [r["decode_tok_per_s"] for r in decode_runs if r["generated_tokens"] > 4]
    result["decode"] = {
        "max_tokens": args.max_tokens,
        "runs": decode_runs,
        "tok_per_s_median": round(statistics.median(decode_tps), 2) if decode_tps else None,
        "tok_per_s_min": min(decode_tps) if decode_tps else None,
        "tok_per_s_max": max(decode_tps) if decode_tps else None,
        "vram_peak_mb": monitor.peak_mb,
        "vram_samples": monitor.samples,
    }
    print(f"  decode median {result['decode']['tok_per_s_median']} tok/s | peak VRAM {monitor.peak_mb} MB")

    # -- repeated inference / memory stability ------------------------
    stability = []
    for i in range(args.stability_runs):
        report = rt.generate(prompt=PROBE_PROMPT, max_tokens=32, temperature=0.0)
        stability.append(
            {
                "run": i + 1,
                "decode_tok_per_s": round(report.decode_tok_per_s, 2),
                "rss_mb": round(proc.memory_info().rss / (1024 * 1024), 1),
                "vram_mb": sampler.sample().as_dict().get("process_dedicated_mb"),
            }
        )
    rss_values = [s["rss_mb"] for s in stability]
    tps_values = [s["decode_tok_per_s"] for s in stability]
    result["stability"] = {
        "runs": stability,
        "rss_first_mb": rss_values[0],
        "rss_last_mb": rss_values[-1],
        "rss_delta_mb": round(rss_values[-1] - rss_values[0], 1),
        "tok_per_s_first": tps_values[0],
        "tok_per_s_last": tps_values[-1],
        "tok_per_s_delta_pct": round((tps_values[-1] - tps_values[0]) / tps_values[0] * 100, 2),
    }
    print(f"  stability: RSS {rss_values[0]} -> {rss_values[-1]} MB "
          f"(delta {result['stability']['rss_delta_mb']} MB), tok/s {tps_values[0]} -> {tps_values[-1]}")

    # -- cancellation -------------------------------------------------
    cancel_event = threading.Event()
    captured: dict[str, object] = {}

    def _runner() -> None:
        try:
            captured["report"] = rt.generate(
                prompt=PROBE_PROMPT,
                max_tokens=args.max_tokens,
                temperature=0.0,
                cancel_event=cancel_event,
            ).as_dict()
        except Exception as exc:  # pragma: no cover - diagnostic path
            captured["error"] = repr(exc)

    worker = threading.Thread(target=_runner, name="kie-cancel", daemon=True)
    worker.start()
    time.sleep(1.2)
    cancel_requested = time.perf_counter()
    cancel_event.set()
    worker.join(timeout=60)
    cancel_latency_ms = (time.perf_counter() - cancel_requested) * 1000.0
    after_cancel = rt.generate(prompt=PROBE_PROMPT, max_tokens=16, temperature=0.0)
    result["cancellation"] = {
        "requested_after_s": 1.2,
        "latency_ms": round(cancel_latency_ms, 2),
        "joined": not worker.is_alive(),
        "run": captured.get("report"),
        "error": captured.get("error"),
        "post_cancel_generation": {
            "text_len": len(after_cancel.text),
            "generated_tokens": after_cancel.generated_tokens,
            "finish": after_cancel.finish,
        },
        "ok": bool(
            isinstance(captured.get("report"), dict)
            and captured["report"].get("cancelled")
            and after_cancel.generated_tokens > 0
        ),
    }
    print(f"  cancel: {cancel_latency_ms:.0f} ms, cancelled="
          f"{isinstance(captured.get('report'), dict) and captured['report'].get('cancelled')}, "
          f"post-cancel tokens={after_cancel.generated_tokens}")

    # -- unload / reload ----------------------------------------------
    rt.unload()
    time.sleep(0.5)
    result["after_unload"] = mem_snapshot(sampler, proc)
    reload_report = rt.load()
    reload_ok = rt.loaded
    reload_generation = rt.generate(prompt=PROBE_PROMPT, max_tokens=8, temperature=0.0)
    result["reload"] = {
        "ok": reload_ok,
        "seconds": round(reload_report.load_seconds, 2),
        "generated_tokens": reload_generation.generated_tokens,
    }
    rt.shutdown()
    sampler.close()
    result["finished_at"] = now_iso()
    result["notes"] = (
        "Cancellation is observed between decode steps; llama.cpp's abort callback is "
        "documented as CPU-only, so Vulkan cancellation latency is one token step."
    )
    print(f"  reload ok={reload_ok} in {reload_report.load_seconds:.2f}s; "
          f"VRAM after unload {result['after_unload']['vram']['process_dedicated_mb']} MB")
    return result


def ambient_report() -> dict[str, object]:
    suspicious = []
    for process in psutil.process_iter(["pid", "name", "cmdline", "cpu_percent"]):
        try:
            cmdline = " ".join(process.info.get("cmdline") or [])
            if any(token in cmdline for token in ("train_walk_forward", "compare_candidates", "PATROR")):
                suspicious.append({"pid": process.info["pid"], "cmdline": cmdline[:300]})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return {
        "cpu_count": psutil.cpu_count(logical=True),
        "cpu_percent_1s": psutil.cpu_percent(interval=1.0),
        "total_ram_gb": round(psutil.virtual_memory().total / (1024**3), 1),
        "available_ram_gb": round(psutil.virtual_memory().available / (1024**3), 1),
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "pid": os.getpid(),
        "platform": platform.platform(),
        "competing_jobs": suspicious,
    }


def boot_backend_api() -> dict[str, object]:
    """Build the FastAPI app in this process: KIE must coexist with the real backend imports."""
    try:
        from app.main import create_app

        app = create_app(start_polling=False, configure_logs=False)
        return {"ok": True, "routes": len(app.routes), "title": app.title}
    except Exception as exc:  # pragma: no cover - environment specific
        return {"ok": False, "error": repr(exc)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", default="both", choices=["vulkan", "cpu", "both"])
    parser.add_argument("--ctx", type=int, default=8192)
    parser.add_argument("--batch", type=int, default=512)
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument("--gpu-layers", type=int, default=None, help="override (default 99 for vulkan, 0 for cpu)")
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--ttft-runs", type=int, default=3)
    parser.add_argument("--ttft-tokens", type=int, default=32)
    parser.add_argument("--stability-runs", type=int, default=10)
    parser.add_argument("--boot-api", action="store_true", help="also build the FastAPI app in-process")
    parser.add_argument("--out-dir", default=str(BACKEND_DIR / "reports" / "kie"))
    return parser


def run_single(name: str, args: argparse.Namespace) -> Path:
    """Measure one backend and write ``phase_a_<name>.json``."""
    manifest = load_manifest()
    model_path = resolve_model(manifest)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    envelope: dict[str, object] = {
        "generated_at": now_iso(),
        "host": ambient_report(),
        "model": {
            "file": model_path.name,
            "size_bytes": model_path.stat().st_size,
            "quant": manifest.model.quant,
            "sha256": manifest.model.sha256,
            "license": manifest.model.license,
        },
        "settings": {
            "n_ctx": args.ctx,
            "n_batch": args.batch,
            "threads": args.threads,
            "reps": args.reps,
            "max_tokens": args.max_tokens,
        },
        "api_boot": boot_backend_api() if args.boot_api else None,
        "results": {},
    }
    print(json.dumps({k: envelope[k] for k in ("generated_at", "model")}, indent=2))
    host = envelope["host"]
    print(f"host: cpu {host['cpu_count']} threads, load {host['cpu_percent_1s']}%, "
          f"ram {host['available_ram_gb']}/{host['total_ram_gb']} GB free, "
          f"competing jobs: {len(host['competing_jobs'])}")
    print(f"settings: ctx={args.ctx} batch={args.batch} reps={args.reps} max_tokens={args.max_tokens}")
    for job in host["competing_jobs"]:
        print(f"  [competing] {job['cmdline'][:120]}")

    try:
        envelope["results"][name] = bench_backend(name, args, manifest, model_path)
    except Exception as exc:
        envelope["results"][name] = {"backend": name, "error": repr(exc)}
        print(f"  !! {name} failed: {exc!r}")

    target = out_dir / f"phase_a_{name}.json"
    target.write_text(json.dumps(envelope, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {target}")
    return target


def comparison_table(out_dir: Path) -> str:
    rows: list[str] = []
    for name in ("vulkan", "cpu"):
        path = out_dir / f"phase_a_{name}.json"
        if not path.is_file():
            rows.append(f"{name:<7} (no result file)")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))["results"][name]
        if "error" in data:
            rows.append(f"{name:<7} error: {data['error'][:90]}")
            continue
        ttft = {entry["target_tokens"]: entry for entry in data["ttft"]}
        rows.append(
            f"{name:<7} load {data['load']['seconds']:>5.2f}s | "
            f"ttft512 {ttft[512]['ttft_ms_median']:>7.0f}ms | "
            f"ingest {ttft[512]['prompt_tok_per_s_median']:>6.1f} tok/s | "
            f"decode {data['decode']['tok_per_s_median']:>6.1f} tok/s | "
            f"peak vram {data['decode']['vram_peak_mb']} MB | "
            f"rss {data['after_load']['rss_mb']} MB"
        )
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_dir = Path(args.out_dir)

    if args.backend != "both":
        run_single(args.backend, args)
        return 0

    # One process per backend: ggml registers its backends globally, so loading the Vulkan
    # and CPU plugin sets into the same process would cross them (and a Vulkan driver
    # fault would take the CPU numbers down with it).
    for name in ("vulkan", "cpu"):
        cmd = [sys.executable, str(Path(__file__).resolve()), "--backend", name,
               "--ctx", str(args.ctx), "--batch", str(args.batch), "--reps", str(args.reps),
               "--max-tokens", str(args.max_tokens), "--ttft-runs", str(args.ttft_runs),
               "--ttft-tokens", str(args.ttft_tokens), "--stability-runs", str(args.stability_runs),
               "--out-dir", str(out_dir)]
        if args.threads:
            cmd += ["--threads", str(args.threads)]
        if args.gpu_layers is not None:
            cmd += ["--gpu-layers", str(args.gpu_layers)]
        if args.boot_api:
            cmd.append("--boot-api")
        print(f"\n>>> {name}: {' '.join(cmd[1:])}")
        subprocess.run(cmd, cwd=str(BACKEND_DIR))  # noqa: S603 - fixed interpreter + own script

    print("\n=== comparison ===")
    print(comparison_table(out_dir))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    combined = {
        "generated_at": now_iso(),
        "runs": {
            name: json.loads((out_dir / f"phase_a_{name}.json").read_text(encoding="utf-8"))
            for name in ("vulkan", "cpu")
            if (out_dir / f"phase_a_{name}.json").is_file()
        },
    }
    target = out_dir / f"phase_a_both_{stamp}.json"
    target.write_text(json.dumps(combined, indent=2, default=str), encoding="utf-8")
    (out_dir / "phase_a_latest.json").write_text(
        json.dumps(combined, indent=2, default=str), encoding="utf-8"
    )
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
