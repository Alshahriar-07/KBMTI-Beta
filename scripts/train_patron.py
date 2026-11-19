"""Reproduce a PATRON checkpoint for KBMTI from public Binance data.

PATRON v1.0.0-beta.1 ships no trained weights. This script:

1. downloads closed BTC/USDT 15m klines from Binance's public REST endpoint,
2. writes the clean parquet PATRON's dataset builder expects,
3. builds the supervised dataset and scaler with PATRON's own script,
4. trains a checkpoint with PATRON's own trainer,
5. copies the checkpoint plus warm-up history into ``backend/models/patron``
   and ``backend/data/patron`` and records provenance.

Run from the repository root with the backend environment:

    backend/.venv/Scripts/python.exe scripts/train_patron.py

Training is CPU-only and intentionally bounded; see ``--help``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
PATRON_DIR = PROJECT_ROOT / "PATRON"
BACKEND_MODEL_DIR = BACKEND_DIR / "models" / "patron"
BACKEND_DATA_DIR = BACKEND_DIR / "data" / "patron"

sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import Settings  # noqa: E402
from app.market_data.binance_history import BinanceHistoryClient  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _epoch_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value).replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def download(start: str, end: str | None) -> tuple[Path, Path, dict]:
    settings = Settings()
    client = BinanceHistoryClient(settings)
    start_ms = _epoch_ms(start)
    end_ms = _epoch_ms(end) if end else None
    print(f"Downloading BTCUSDT 15m from {start} to {end or 'now'} ...", flush=True)
    rows = client.range("BTCUSDT", "15m", start_ms, end_ms)
    if len(rows) < 20_000:
        raise SystemExit(
            f"Only {len(rows)} candles were returned; at least 20,000 are needed for a "
            "usable train/validation/test split."
        )
    clean_dir = PATRON_DIR / "data" / "clean" / "BTCUSDT"
    clean_dir.mkdir(parents=True, exist_ok=True)
    clean_path = clean_dir / "15m.parquet"
    BACKEND_DATA_DIR.mkdir(parents=True, exist_ok=True)
    warmup_path = BACKEND_DATA_DIR / "BTCUSDT_15m.parquet"

    import pandas as pd

    frame = pd.DataFrame(
        {
            "timestamp_open": pd.to_datetime([row.open_time_ms for row in rows], unit="ms", utc=True),
            "timestamp_close": pd.to_datetime([row.close_time_ms for row in rows], unit="ms", utc=True),
            "open": [row.open for row in rows],
            "high": [row.high for row in rows],
            "low": [row.low for row in rows],
            "close": [row.close for row in rows],
            "volume": [row.volume for row in rows],
            "is_gap": 0,
        }
    )
    frame.to_parquet(clean_path, index=False)
    frame.to_parquet(warmup_path, index=False)
    meta = {
        "source": "binance-spot-public-rest",
        "endpoint": settings.binance_rest_url,
        "interval": "15m",
        "rows": int(len(frame)),
        "start": frame["timestamp_open"].iloc[0].isoformat(),
        "end": frame["timestamp_open"].iloc[-1].isoformat(),
        "clean_sha256": _sha256(clean_path),
        "history_requests": client.status()["requests"],
        "downloaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    print(f"Saved {len(frame):,} candles -> {clean_path}", flush=True)
    return clean_path, warmup_path, meta


def build_dataset(clean_path: Path, stride: int) -> None:
    command = [
        sys.executable,
        "scripts/build_dataset.py",
        "--config",
        "configs/model_config.yaml",
        "--clean",
        str(clean_path),
        "--stride",
        str(stride),
    ]
    print("Building PATRON dataset:", " ".join(command), flush=True)
    subprocess.run(command, cwd=PATRON_DIR, check=True)


def train(run_name: str, epochs: int, stride: int, threads: int) -> Path:
    command = [
        sys.executable,
        "-m",
        "patron",
        "train",
        "--config",
        "configs/model_config.yaml",
        "--run-name",
        run_name,
        "--epochs",
        str(epochs),
        "--train-stride",
        str(stride),
        "--threads",
        str(threads),
    ]
    print("Training PATRON:", " ".join(command), flush=True)
    subprocess.run(command, cwd=PATRON_DIR, check=True)
    experiments = PATRON_DIR / "experiments"
    candidates = sorted(
        (
            path
            for path in experiments.glob(f"{run_name}*")
            if path.is_dir() and (path / "best.pt").is_file()
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise SystemExit(f"Training finished but no {run_name}*/best.pt was found.")
    return candidates[0] / "best.pt"


def publish(checkpoint: Path, warmup_path: Path, run_name: str, meta: dict) -> Path:
    BACKEND_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKEND_MODEL_DIR / "best.pt"
    shutil.copy2(checkpoint, target)
    experiment = checkpoint.parent
    history = experiment / "training_history.json"
    record = {
        **meta,
        "checkpoint_source": str(checkpoint),
        "checkpoint_target": str(target),
        "checkpoint_sha256": _sha256(target),
        "checkpoint_bytes": target.stat().st_size,
        "run_name": run_name,
        "training_history": json.loads(history.read_text(encoding="utf-8"))
        if history.is_file()
        else None,
        "note": (
            "Locally trained from public Binance data with PATRON's shipped pipeline. "
            "This is not the (unreleased) PATRON reference checkpoint; validate any "
            "metric before production use."
        ),
    }
    (BACKEND_MODEL_DIR / "MODEL_PROVENANCE.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8"
    )
    warmup_target = BACKEND_DATA_DIR / "BTCUSDT_15m.parquet"
    if warmup_path.resolve() != warmup_target.resolve():
        shutil.copy2(warmup_path, warmup_target)
    print(f"Checkpoint -> {target}", flush=True)
    print(f"Warm-up     -> {warmup_target}", flush=True)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2024-01-01", help="ISO date, inclusive")
    parser.add_argument("--end", default=None, help="ISO date, exclusive (default: now)")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--stride", type=int, default=4, help="dataset/window stride")
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--run-name", default="kbmti_patron_v1")
    parser.add_argument("--clean", default=None, help="reuse an existing clean parquet")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    if args.clean:
        clean_path = Path(args.clean)
        warmup_path = BACKEND_DATA_DIR / "BTCUSDT_15m.parquet"
        import pandas as pd

        frame = pd.read_parquet(clean_path)
        warmup_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(warmup_path, index=False)
        meta = {
            "source": "existing-clean-parquet",
            "rows": int(len(frame)),
            "start": str(frame["timestamp_open"].iloc[0]),
            "end": str(frame["timestamp_open"].iloc[-1]),
            "clean_sha256": _sha256(clean_path),
        }
    elif args.skip_download:
        clean_path = PATRON_DIR / "data" / "clean" / "BTCUSDT" / "15m.parquet"
        warmup_path = BACKEND_DATA_DIR / "BTCUSDT_15m.parquet"
        if not clean_path.is_file():
            raise SystemExit(f"--skip-download was given but {clean_path} is missing.")
        meta = {"source": "existing-clean-parquet", "clean_sha256": _sha256(clean_path)}
    else:
        clean_path, warmup_path, meta = download(args.start, args.end)

    if not args.skip_build:
        build_dataset(clean_path, args.stride)
    checkpoint = train(args.run_name, args.epochs, args.stride, args.threads)
    publish(checkpoint, warmup_path, args.run_name, meta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
