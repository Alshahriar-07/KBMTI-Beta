"""Pinned artifact manifest for the KIE runtime.

Everything KIE loads from disk is described here and verified before use:

* the llama.cpp release tag and the SHA-256 of each downloaded archive,
* the runtime directory it was extracted to (per backend),
* the GGUF model file, its size, SHA-256 and license.

The manifest lives at ``backend/models/kie/manifest.json`` and is written by
``scripts/kie_fetch_runtime.py``. Artifacts are git-ignored; the manifest is the pin.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[3]
MODELS_ROOT = BACKEND_DIR / "models" / "kie"
MANIFEST_PATH = MODELS_ROOT / "manifest.json"


class ManifestError(RuntimeError):
    """Raised when the manifest is missing or does not describe a usable artifact."""


@dataclass(frozen=True)
class RuntimeVariant:
    backend: str
    tag: str
    directory: str
    archive: str
    archive_sha256: str

    @property
    def path(self) -> Path:
        return MODELS_ROOT / "runtime" / self.directory


@dataclass(frozen=True)
class ModelArtifact:
    repo: str
    filename: str
    quant: str
    license: str
    size_bytes: int
    sha256: str

    @property
    def path(self) -> Path:
        return MODELS_ROOT / "models" / self.filename


@dataclass(frozen=True)
class KieManifest:
    tag: str
    source: str
    variants: dict[str, RuntimeVariant]
    model: ModelArtifact

    def runtime(self, backend: str) -> RuntimeVariant:
        variant = self.variants.get(backend)
        if variant is None:
            raise ManifestError(f"backend '{backend}' is not in the manifest (have: {sorted(self.variants)})")
        if not (variant.path / "llama.dll").is_file():
            raise ManifestError(
                f"{backend} runtime missing at {variant.path}; run scripts/kie_fetch_runtime.py --backend {backend}"
            )
        return variant


def load_manifest(path: Path | None = None) -> KieManifest:
    target = path or MANIFEST_PATH
    if not target.is_file():
        raise ManifestError(f"manifest not found at {target}; run scripts/kie_fetch_runtime.py")
    data = json.loads(target.read_text(encoding="utf-8"))
    variants = {
        name: RuntimeVariant(
            backend=name,
            tag=data["runtime"]["tag"],
            directory=entry["directory"],
            archive=entry["archive"],
            archive_sha256=entry["archive_sha256"],
        )
        for name, entry in data["runtime"]["variants"].items()
    }
    model = data["model"]
    return KieManifest(
        tag=data["runtime"]["tag"],
        source=data["runtime"]["source"],
        variants=variants,
        model=ModelArtifact(
            repo=model["repo"],
            filename=model["filename"],
            quant=model["quant"],
            license=model["license"],
            size_bytes=int(model["size_bytes"]),
            sha256=model["sha256"],
        ),
    )


def resolve_model(manifest: KieManifest) -> Path:
    path = manifest.model.path
    if not path.is_file():
        raise ManifestError(f"model not found at {path}; run scripts/kie_fetch_runtime.py")
    size = path.stat().st_size
    if size != manifest.model.size_bytes:
        raise ManifestError(
            f"model size mismatch for {path.name}: {size} bytes on disk, {manifest.model.size_bytes} pinned "
            "(partial or truncated download?)"
        )
    return path
