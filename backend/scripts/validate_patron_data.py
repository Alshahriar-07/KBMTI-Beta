"""Validate PATRON's raw candles and supervised dataset, reproducibly.

Writes a versioned quality manifest with hashes, split boundaries and a causal
feature check. It never mutates the raw parquet and never trains a model.

Run from ``backend``::

    PYTHONPATH=. .venv/Scripts/python.exe scripts/validate_patron_data.py \
        --raw data/patron/BTCUSDT_15m.parquet \
        --dataset ../PATRON/data/features/BTCUSDT_dataset.parquet \
        --out ../docs/AI_TRADING_UPGRADE/PATRON_DATASET_QUALITY.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from patron.config import load_config
from patron.datasets.splits import chronological_split
from patron.features.builder import build_features
from patron.features.schema import FEATURE_ORDER

VERSION = "btcusdt-15m-v1.0.0"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _raw_checks(frame: pd.DataFrame) -> dict[str, Any]:
    required = {"timestamp_open", "timestamp_close", "open", "high", "low", "close", "volume"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise SystemExit(f"raw data missing columns: {missing}")
    frame = frame.copy()
    frame["timestamp_open"] = pd.to_datetime(frame["timestamp_open"], utc=True)
    frame["timestamp_close"] = pd.to_datetime(frame["timestamp_close"], utc=True)
    deltas = frame["timestamp_open"].diff().dropna()
    bad_ohlc = (
        (frame["high"] < frame[["open", "close"]].max(axis=1))
        | (frame["low"] > frame[["open", "close"]].min(axis=1))
        | (frame["high"] < frame["low"])
    )
    volume = frame["volume"].astype(float)
    median = volume.median()
    mad = (volume - median).abs().median()
    abnormal = volume > median + 25 * max(mad, 1e-9)
    return {
        "rows": int(len(frame)),
        "start": frame["timestamp_open"].iloc[0].isoformat(),
        "end": frame["timestamp_open"].iloc[-1].isoformat(),
        "timezone_aware": bool(frame["timestamp_open"].dt.tz is not None),
        "chronological": bool(frame["timestamp_open"].is_monotonic_increasing),
        "duplicate_timestamps": int(frame["timestamp_open"].duplicated().sum()),
        "non_15m_steps": int((deltas != pd.Timedelta(minutes=15)).sum()),
        "gap_count": int((deltas > pd.Timedelta(minutes=15)).sum()),
        "invalid_ohlc_rows": int(bad_ohlc.sum()),
        "negative_volume_rows": int((volume < 0).sum()),
        "null_cells": int(frame[list(required)].isna().sum().sum()),
        "abnormal_volume_rows": int(abnormal.sum()),
        "abnormal_volume_note": "volume > median + 25*MAD; flagged, never silently removed",
        # Binance closeTime is openTime + 899999 ms, i.e. one millisecond before
        # the next open. Preserve that convention and report it explicitly.
        "close_offset_seconds": float(
            (frame["timestamp_close"] - frame["timestamp_open"]).dt.total_seconds().median()
        ),
    }


def _target_alignment(raw: pd.DataFrame, dataset: pd.DataFrame) -> dict[str, Any]:
    close = raw["close"].to_numpy(dtype=float)
    high = raw["high"].to_numpy(dtype=float)
    low = raw["low"].to_numpy(dtype=float)
    checks: dict[str, Any] = {}
    for field, values in (("close", close), ("high", high), ("low", low)):
        for step in range(1, 7):
            column = f"tgt_{field}_{step}"
            if column not in dataset.columns:
                checks[column] = {"available": False}
                continue
            actual = np.full(len(raw), np.nan)
            valid = np.arange(len(raw)) + step < len(raw)
            future = np.minimum(np.arange(len(raw)) + step, len(raw) - 1)
            actual[valid] = values[future][valid] / close[valid] - 1.0
            diff = np.abs(dataset[column].to_numpy(dtype=float) - actual)
            checks[column] = {
                "available": True,
                "max_abs_diff": float(np.nanmax(diff)) if np.isfinite(diff).any() else None,
                "matches": bool(np.nanmax(diff) < 1e-12),
            }
    return {
        "rows_equal": len(raw) == len(dataset),
        "timestamps_equal": bool(
            (raw["timestamp_open"].to_numpy() == dataset["timestamp_open"].to_numpy()).all()
        ),
        "targets": checks,
        "all_targets_match": all(
            item.get("matches", True) for item in checks.values()
        ),
    }


def _causal_feature_check(raw: pd.DataFrame, atr_period: int) -> dict[str, Any]:
    """Compare row k-1 from all data with the last row when all future is deleted."""
    full_frame = build_features(
        raw, atr_period=atr_period, volume_baseline=96
    )
    results = []
    for cutoff in (5000, 50_000, 90_000):
        if cutoff >= len(raw):
            continue
        full = full_frame.iloc[cutoff - 1]
        truncated = build_features(
            raw.iloc[:cutoff], atr_period=atr_period, volume_baseline=96
        ).iloc[-1]
        diffs = {
            feature: float(abs(float(full[feature]) - float(truncated[feature])))
            for feature in FEATURE_ORDER
        }
        results.append(
            {
                "cutoff_row": cutoff,
                "max_abs_diff": max(diffs.values()),
                "causal": max(diffs.values()) < 1e-12,
            }
        )
    return {
        "checks": results,
        "passed": all(item["causal"] for item in results),
        "note": "Features at bar k are identical when all candles after k are deleted.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", default="data/patron/BTCUSDT_15m.parquet")
    parser.add_argument("--dataset", default="../PATRON/data/features/BTCUSDT_dataset.parquet")
    parser.add_argument("--config", default="../PATRON/configs/model_config.yaml")
    parser.add_argument(
        "--out", default="../docs/AI_TRADING_UPGRADE/PATRON_DATASET_QUALITY.json"
    )
    args = parser.parse_args()

    raw_path = Path(args.raw)
    dataset_path = Path(args.dataset)
    raw = pd.read_parquet(raw_path)
    dataset = pd.read_parquet(dataset_path)
    cfg = load_config(args.config)
    raw["timestamp_open"] = pd.to_datetime(raw["timestamp_open"], utc=True)
    raw["timestamp_close"] = pd.to_datetime(raw["timestamp_close"], utc=True)

    quality = _raw_checks(raw)
    alignment = _target_alignment(raw, dataset)
    causal = _causal_feature_check(raw, cfg.forecast.barrier.atr_period)

    # Reproduce PATRON's chronological split on the dataset's valid window ends.
    frame = build_features(
        raw,
        atr_period=cfg.forecast.barrier.atr_period,
        volume_baseline=cfg.sequence_length,
        feature_order=cfg.feature_order,
    )
    feature_ok = (
        pd.Series(frame["feature_valid"].astype(int))
        .rolling(cfg.sequence_length, min_periods=cfg.sequence_length)
        .sum()
        .to_numpy()
        == cfg.sequence_length
    )
    targets_present = np.isfinite(
        dataset[[f"tgt_close_{s}" for s in range(1, cfg.horizon + 1)]].to_numpy()
    ).all(axis=1)
    positions = np.flatnonzero(feature_ok & targets_present)
    split = chronological_split(
        len(positions), purge=cfg.validation.purge_bars, embargo=cfg.validation.embargo_bars
    )

    def boundary(indices: np.ndarray) -> dict[str, Any]:
        if len(indices) == 0:
            return {"windows": 0}
        first = int(positions[indices[0]])
        last = int(positions[indices[-1]])
        return {
            "windows": int(len(indices)),
            "first_bar": raw["timestamp_open"].iloc[first].isoformat(),
            "last_bar": raw["timestamp_open"].iloc[last].isoformat(),
            "first_index": first,
            "last_index": last,
        }

    report = {
        "dataset_version": VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "raw_path": str(raw_path.resolve()),
        "raw_sha256": _sha256(raw_path),
        "dataset_path": str(dataset_path.resolve()),
        "dataset_sha256": _sha256(dataset_path),
        "raw": quality,
        "target_alignment": alignment,
        "causal_feature_check": causal,
        "split": {
            "method": cfg.validation.method,
            "purge_bars": cfg.validation.purge_bars,
            "embargo_bars": cfg.validation.embargo_bars,
            "train": boundary(split.train),
            "validation": boundary(split.val),
            "test": boundary(split.test),
        },
        "conclusion": {
            "raw_data_usable": quality["duplicate_timestamps"] == 0
            and quality["non_15m_steps"] == 0
            and quality["invalid_ohlc_rows"] == 0
            and quality["negative_volume_rows"] == 0
            and quality["null_cells"] == 0,
            "targets_aligned": alignment["all_targets_match"],
            "features_causal": causal["passed"],
            "abnormal_volume_policy": "flagged only; authentic market spikes are retained",
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("raw", "conclusion", "split")}, indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
