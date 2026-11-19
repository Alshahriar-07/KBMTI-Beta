"""Fetch and pin the KIE runtime artifacts.

Downloads the official llama.cpp Windows builds (Vulkan and CPU) and the Qwen3-4B Q4_K_M
GGUF, verifies SHA-256, extracts the DLLs and writes ``backend/models/kie/manifest.json``.

Nothing is compiled: these are the release binaries published for tag ``b12503``.

Usage (from ``backend/``):

    .venv/Scripts/python.exe scripts/kie_fetch_runtime.py --backend vulkan,cpu
    .venv/Scripts/python.exe scripts/kie_fetch_runtime.py --verify-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
MODELS_ROOT = BACKEND_DIR / "models" / "kie"
RUNTIME_ROOT = MODELS_ROOT / "runtime"
MODEL_ROOT = MODELS_ROOT / "models"
MANIFEST_PATH = MODELS_ROOT / "manifest.json"

TAG = "b12503"
SOURCE = f"https://github.com/ggml-org/llama.cpp/releases/tag/{TAG}"
DOWNLOAD_BASE = f"https://github.com/ggml-org/llama.cpp/releases/download/{TAG}"

# SHA-256 of the archives as published for tag b12503 (recorded 2026-11-18).
VARIANTS: dict[str, dict[str, str]] = {
    "vulkan": {
        "archive": f"llama-{TAG}-bin-win-vulkan-x64.zip",
        "directory": f"{TAG}-vulkan",
        "archive_sha256": "6c83027548f989a4d5c9502b31b580dc5e1254998bd49c1d78e85f316900d118",
    },
    "cpu": {
        "archive": f"llama-{TAG}-bin-win-cpu-x64.zip",
        "directory": f"{TAG}-cpu",
        "archive_sha256": "64bee9b6fece8e66c665c40290cbb84706af23c670041d024b56a71a39859d77",
    },
}

MODEL = {
    "repo": "Qwen/Qwen3-4B-GGUF",
    "filename": "Qwen3-4B-Q4_K_M.gguf",
    "quant": "Q4_K_M",
    "license": "Apache-2.0",
    "size_bytes": 2497280256,
    "url": "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf",
}


def sha256(path: Path, chunk: int = 8 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(url) as response, partial.open("wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while chunk := response.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 / total
                print(f"\r  {target.name}: {done / 1e6:7.1f}/{total / 1e6:.1f} MB ({pct:5.1f}%)", end="", flush=True)
    print()
    partial.replace(target)


def ensure_archive(name: str, spec: dict[str, str]) -> Path:
    archive = RUNTIME_ROOT / spec["archive"]
    if archive.is_file():
        if sha256(archive) == spec["archive_sha256"]:
            print(f"[ok] {archive.name} (sha256 verified)")
            return archive
        print(f"[warn] {archive.name} hash mismatch, re-downloading")
        archive.unlink()
    print(f"[dl] {spec['archive']} from llama.cpp {TAG}")
    download(f"{DOWNLOAD_BASE}/{spec['archive']}", archive)
    actual = sha256(archive)
    if actual != spec["archive_sha256"]:
        raise SystemExit(f"sha256 mismatch for {archive.name}: {actual} != {spec['archive_sha256']}")
    print(f"[ok] {archive.name} sha256 {actual}")
    return archive


def extract(archive: Path, target_name: str) -> Path:
    target = RUNTIME_ROOT / target_name
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(target)
    if not (target / "llama.dll").is_file():
        raise SystemExit(f"llama.dll missing after extracting {archive.name}")
    # The .exe tools (llama-cli, llama-server, ...) are not used: KIE embeds the DLL only.
    removed = 0
    for exe in target.glob("*.exe"):
        exe.unlink()
        removed += 1
    print(f"[ok] extracted {archive.name} -> {target.relative_to(BACKEND_DIR)} ({removed} exe files removed)")
    return target


def ensure_model(verify_only: bool) -> dict[str, object]:
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    path = MODEL_ROOT / MODEL["filename"]
    if not path.is_file() or path.stat().st_size != MODEL["size_bytes"]:
        if verify_only:
            raise SystemExit(f"model missing or wrong size at {path}")
        if path.is_file():
            print(f"[warn] {path.name} has {path.stat().st_size} bytes, expected {MODEL['size_bytes']}; re-downloading")
            path.unlink()
        print(f"[dl] {MODEL['filename']} ({MODEL['size_bytes'] / 1e9:.2f} GB) from {MODEL['repo']}")
        download(MODEL["url"], path)
    digest = sha256(path)
    print(f"[ok] {path.name} {MODEL['size_bytes']} bytes sha256 {digest}")
    return {
        "repo": MODEL["repo"],
        "filename": MODEL["filename"],
        "quant": MODEL["quant"],
        "license": MODEL["license"],
        "size_bytes": MODEL["size_bytes"],
        "sha256": digest,
        "source": f"https://huggingface.co/{MODEL['repo']}",
    }


def write_manifest(model_info: dict[str, object], backends: list[str]) -> None:
    data = {
        "runtime": {
            "tag": TAG,
            "source": SOURCE,
            "variants": {name: VARIANTS[name] for name in backends},
        },
        "model": model_info,
    }
    MANIFEST_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"[ok] wrote {MANIFEST_PATH.relative_to(BACKEND_DIR)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", default="vulkan,cpu", help="comma separated: vulkan,cpu")
    parser.add_argument("--skip-model", action="store_true", help="only fetch the runtime DLLs")
    parser.add_argument("--verify-only", action="store_true", help="verify what is on disk, download nothing")
    parser.add_argument("--check-model-hash", action="store_true", help="recompute the GGUF hash and compare")
    args = parser.parse_args(argv)

    backends = [b.strip() for b in args.backend.split(",") if b.strip()]
    unknown = [b for b in backends if b not in VARIANTS]
    if unknown:
        raise SystemExit(f"unknown backend(s): {unknown}")

    if args.verify_only:
        for name in backends:
            archive = RUNTIME_ROOT / VARIANTS[name]["archive"]
            if not archive.is_file():
                raise SystemExit(f"missing archive: {archive}")
            actual = sha256(archive)
            expected = VARIANTS[name]["archive_sha256"]
            status = "ok" if actual == expected else "MISMATCH"
            print(f"[{status}] {archive.name} {actual}")
            if actual != expected:
                return 1
        if not args.skip_model:
            path = MODEL_ROOT / MODEL["filename"]
            if not path.is_file() or path.stat().st_size != MODEL["size_bytes"]:
                raise SystemExit(f"model missing or wrong size at {path}")
            if args.check_model_hash:
                print(f"[ok] {path.name} sha256 {sha256(path)}")
        print("verification complete")
        return 0

    for name in backends:
        archive = ensure_archive(name, VARIANTS[name])
        extract(archive, VARIANTS[name]["directory"])

    if args.skip_model:
        print("model download skipped")
        return 0

    model_info = ensure_model(verify_only=False)
    write_manifest(model_info, backends)
    return 0


if __name__ == "__main__":
    sys.exit(main())
