"""Measured audit of the deployed PATRON checkpoint against held-out candles.

This script does not train or modify anything. It rebuilds PATRON's own causal
features, runs the checkpoint on the chronological test split, and compares the
forecast quantiles with the realised candles and simple baselines. Results are
written as JSON so the audit report quotes measured values only.

Run from ``backend``:

    PYTHONPATH=. .venv/Scripts/python.exe scripts/patron_audit.py \
        --checkpoint models/patron/best.pt \
        --data data/patron/BTCUSDT_15m.parquet \
        --out ../docs/AI_TRADING_UPGRADE/PATRON_AUDIT_METRICS.json
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

from patron.config import PatronConfig
from patron.datasets.splits import chronological_split
from patron.features.builder import build_features
from patron.features.schema import FEATURE_ORDER
from patron.models.patron_net import build_model
from patron.training.trainer import load_checkpoint


def _quantile_loss(pred: np.ndarray, target: np.ndarray, q: float) -> float:
    error = target - pred
    return float(np.mean(np.maximum(q * error, (q - 1.0) * error)))


def _directional_accuracy(pred_return: np.ndarray, actual_return: np.ndarray) -> dict[str, float]:
    mask = np.abs(actual_return) > 1e-4  # 1 bp: ignore doji-like realised moves
    if mask.sum() == 0:
        return {"all": float("nan"), "non_neutral": float("nan"), "n_non_neutral": 0}
    return {
        "all": float(np.mean(np.sign(pred_return) == np.sign(actual_return))),
        "non_neutral": float(np.mean(np.sign(pred_return[mask]) == np.sign(actual_return[mask]))),
        "n_non_neutral": int(mask.sum()),
    }


def _summarise(
    pred: np.ndarray, actual: np.ndarray, q10: np.ndarray, q90: np.ndarray
) -> dict[str, Any]:
    """pred/actual are [N, H, F] relative-to-reference values, F=(high,low,close)."""
    out: dict[str, Any] = {}
    for field_index, field in enumerate(("high", "low", "close")):
        p = pred[:, :, field_index]
        a = actual[:, :, field_index]
        error = a - p
        out[field] = {
            "mae_bps": float(np.mean(np.abs(error)) * 10_000),
            "rmse_bps": float(np.sqrt(np.mean(error**2)) * 10_000),
            "bias_bps": float(np.mean(error) * 10_000),
            "correlation": float(np.corrcoef(p.ravel(), a.ravel())[0, 1])
            if np.std(p) > 0 and np.std(a) > 0
            else 0.0,
        }
    close = out["close"]
    close.update(_directional_accuracy(pred[:, :, 2], actual[:, :, 2]))
    # Quantile metrics for the close path.
    q10_close, q50, q90_close = q10[:, :, 2], pred[:, :, 2], q90[:, :, 2]
    target = actual[:, :, 2]
    close["pinball_q10"] = _quantile_loss(q10_close, target, 0.1)
    close["pinball_q50"] = _quantile_loss(q50, target, 0.5)
    close["pinball_q90"] = _quantile_loss(q90_close, target, 0.9)
    close["pinball_mean"] = (close["pinball_q10"] + close["pinball_q50"] + close["pinball_q90"]) / 3.0
    close["coverage_80"] = float(np.mean((target >= q10_close) & (target <= q90_close)))
    close["mean_interval_width_bps"] = float(np.mean(q90_close - q10_close) * 10_000)
    close["predicted_std_bps"] = float(np.std(q50) * 10_000)
    close["actual_std_bps"] = float(np.std(target) * 10_000)
    return out


def _make_dataset(
    cfg: PatronConfig, frame: pd.DataFrame, candles: pd.DataFrame
) -> tuple[np.ndarray, np.ndarray]:
    """Return (target [N,H,3], positions) using PATRON's label semantics."""
    horizon = cfg.horizon
    seq = cfg.sequence_length
    close = candles["close"].to_numpy(dtype=np.float64)
    high = candles["high"].to_numpy(dtype=np.float64)
    low = candles["low"].to_numpy(dtype=np.float64)
    n = len(frame)
    targets = np.full((n, horizon, 3), np.nan, dtype=np.float64)
    for step in range(1, horizon + 1):
        valid = np.arange(n) + step < n
        fut = np.minimum(np.arange(n) + step, n - 1)
        targets[valid, step - 1, 0] = high[fut][valid] / close[valid] - 1.0
        targets[valid, step - 1, 1] = low[fut][valid] / close[valid] - 1.0
        targets[valid, step - 1, 2] = close[fut][valid] / close[valid] - 1.0
    valid = frame["feature_valid"].to_numpy(dtype=bool) & np.isfinite(targets).all(axis=(1, 2))
    positions = np.flatnonzero(valid)
    positions = positions[positions >= seq - 1]
    return targets, positions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default="models/patron/best.pt")
    parser.add_argument("--data", default="data/patron/BTCUSDT_15m.parquet")
    parser.add_argument("--out", default="../docs/AI_TRADING_UPGRADE/PATRON_AUDIT_METRICS.json")
    parser.add_argument("--sample", type=int, default=4000, help="max test windows")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--threads", type=int, default=6)
    args = parser.parse_args()

    torch.set_num_threads(max(1, args.threads))
    checkpoint = load_checkpoint(args.checkpoint)
    cfg = PatronConfig.model_validate(checkpoint["config"])
    candles = pd.read_parquet(args.data)
    candles["timestamp_open"] = pd.to_datetime(candles["timestamp_open"], utc=True)
    candles["timestamp_close"] = pd.to_datetime(candles["timestamp_close"], utc=True)

    started = time.perf_counter()
    frame = build_features(
        candles,
        atr_period=cfg.forecast.barrier.atr_period,
        volume_baseline=cfg.sequence_length,
        feature_order=cfg.feature_order,
    )
    targets, positions = _make_dataset(cfg, frame, candles)
    split = chronological_split(
        len(positions), purge=cfg.validation.purge_bars, embargo=cfg.validation.embargo_bars
    )
    test_positions = positions[split.test]
    step = max(1, math.ceil(len(test_positions) / args.sample))
    eval_positions = test_positions[::step]

    model = build_model(cfg)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()
    raw = frame[list(FEATURE_ORDER)].to_numpy(dtype=np.float64)
    # PATRON stores the fitted scaler in the checkpoint; reproduce it exactly.
    from patron.features.scaler import RobustFeatureScaler

    scaler = RobustFeatureScaler.load_from_dict(checkpoint["scaler"])
    scaled = scaler.transform(raw)

    x_batches = []
    for end in eval_positions:
        x_batches.append(scaled[end - cfg.sequence_length + 1 : end + 1])
    x = np.stack(x_batches).astype(np.float32)

    predictions = []
    forward_started = time.perf_counter()
    with torch.no_grad():
        for start in range(0, len(x), args.batch_size):
            out = model(torch.from_numpy(x[start : start + args.batch_size]))
            predictions.append(out["quantile"].numpy())
    forward_seconds = time.perf_counter() - forward_started
    quantiles = np.concatenate(predictions, axis=0)  # [N,H,3,Q] (high,low,close)x(q10,q50,q90)
    realised = targets[eval_positions]  # [N,H,3]
    pred_q10 = quantiles[:, :, :, 0]
    pred_q90 = quantiles[:, :, :, 2]
    pred_q50 = quantiles[:, :, :, 1]

    report: dict[str, Any] = {
        "checkpoint": str(Path(args.checkpoint).resolve()),
        "checkpoint_epoch": checkpoint.get("epoch"),
        "checkpoint_best_epoch": checkpoint.get("best_epoch"),
        "checkpoint_val_loss": checkpoint.get("val_loss"),
        "data": str(Path(args.data).resolve()),
        "data_rows": int(len(candles)),
        "data_start": candles["timestamp_open"].iloc[0].isoformat(),
        "data_end": candles["timestamp_open"].iloc[-1].isoformat(),
        "test_windows_available": int(len(test_positions)),
        "test_windows_evaluated": int(len(eval_positions)),
        "test_first_bar": candles["timestamp_open"].iloc[int(eval_positions[0])].isoformat(),
        "test_last_bar": candles["timestamp_open"].iloc[int(eval_positions[-1])].isoformat(),
        "feature_build_seconds": round(time.perf_counter() - started, 2),
        "model_forward_seconds": round(forward_seconds, 2),
        "model_windows_per_second": round(len(x) / max(forward_seconds, 1e-9), 1),
        "overall": _summarise(pred_q50, realised, pred_q10, pred_q90),
        "by_step": {},
        "baselines": {},
        "candle_geometry": {},
    }

    for step_index in range(cfg.horizon):
        report["by_step"][str(step_index + 1)] = _summarise(
            pred_q50[:, step_index : step_index + 1, :],
            realised[:, step_index : step_index + 1, :],
            pred_q10[:, step_index : step_index + 1, :],
            pred_q90[:, step_index : step_index + 1, :],
        )

    close_realised = realised[:, :, 2]
    # Baseline 1: persistence (last close unchanged).
    report["baselines"]["persistence"] = {
        "mae_bps": float(np.mean(np.abs(close_realised)) * 10_000),
        "directional_accuracy": _directional_accuracy(np.zeros_like(close_realised), close_realised),
    }
    # Baseline 2: repeat the last observed bar return.
    last_return = (frame["close"].to_numpy() / frame["close"].shift(1).to_numpy() - 1.0)[eval_positions]
    prev = np.repeat(last_return[:, None], cfg.horizon, axis=1)
    report["baselines"]["previous_candle"] = {
        "mae_bps": float(np.mean(np.abs(close_realised - prev)) * 10_000),
        "directional_accuracy": _directional_accuracy(prev, close_realised),
    }
    # Baseline 3: mean of the last 96 close-to-close returns (drift).
    returns = np.nan_to_num(frame["close"].pct_change().to_numpy())
    rolling_mean = pd.Series(returns).rolling(cfg.sequence_length, min_periods=cfg.sequence_length).mean().to_numpy()
    drift = np.repeat(rolling_mean[eval_positions][:, None], cfg.horizon, axis=1)
    report["baselines"]["rolling_mean_96"] = {
        "mae_bps": float(np.mean(np.abs(close_realised - drift)) * 10_000),
        "directional_accuracy": _directional_accuracy(drift, close_realised),
    }
    report["baselines"]["model"] = {
        "mae_bps": report["overall"]["close"]["mae_bps"],
        "directional_accuracy": {
            "all": report["overall"]["close"]["all"],
            "non_neutral": report["overall"]["close"]["non_neutral"],
            "n_non_neutral": report["overall"]["close"]["n_non_neutral"],
        },
    }

    # Derived-candle geometry, exactly as PatronForecastProvider builds it.
    ref_close = frame["close"].to_numpy()[eval_positions]
    derived_high = pred_q50[:, :, 0] * ref_close[:, None]
    derived_low = pred_q50[:, :, 1] * ref_close[:, None]
    derived_close = pred_q50[:, :, 2] * ref_close[:, None]
    derived_open = np.concatenate(
        [np.full((len(ref_close), 1), 0.0), derived_close[:, :-1]], axis=1
    )
    derived_open[:, 0] = ref_close
    report["candle_geometry"] = {
        "high_below_open_close_raw": int(np.sum(derived_high < np.maximum(derived_open, derived_close))),
        "low_above_open_close_raw": int(np.sum(derived_low > np.minimum(derived_open, derived_close))),
        "total_candles": int(derived_high.size),
        "high_below_open_close_pct": float(
            np.mean(derived_high < np.maximum(derived_open, derived_close)) * 100
        ),
        "low_above_open_close_pct": float(
            np.mean(derived_low > np.minimum(derived_open, derived_close)) * 100
        ),
        "quantile_order_violations": int(
            np.sum(quantiles[:, :, :, 0] > quantiles[:, :, :, 1])
            + np.sum(quantiles[:, :, :, 1] > quantiles[:, :, :, 2])
        ),
        "realised_high_below_ref_pct": float(np.mean(realised[:, :, 0] < 0) * 100),
        "realised_low_above_ref_pct": float(np.mean(realised[:, :, 1] > 0) * 100),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("test_windows_evaluated", "overall", "baselines")}, indent=2))
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
