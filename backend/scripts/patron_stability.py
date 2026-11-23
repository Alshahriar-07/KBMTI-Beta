"""Rolling out-of-sample stability audit for two PATRON checkpoints.

This is **not** fold-wise retraining. It evaluates the promoted candidate and the
previous champion, unchanged, over chronological blocks of the untouched test
split, and compares them with last-close persistence, previous-candle repetition
and a 96-bar mean-return drift. Fold-wise retraining is intentionally out of scope:
the approved candidate was already trained and promoted, and retraining every fold
on CPU would take roughly an hour per fold.

Everything here is read-only. No checkpoint is written or replaced.

Run from ``backend``::

    PYTHONPATH=. .venv/Scripts/python.exe scripts/patron_stability.py \
        --out ../docs/AI_TRADING_UPGRADE/PATRON_ROLLING_STABILITY.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

from patron.config import PatronConfig
from patron.datasets.splits import chronological_split
from patron.evaluation.regimes import add_regimes
from patron.features.builder import build_features
from patron.features.scaler import RobustFeatureScaler
from patron.features.schema import FEATURE_ORDER
from patron.models.patron_net import build_model
from patron.training.trainer import load_checkpoint


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_model(path: Path, expected: PatronConfig) -> tuple[Any, RobustFeatureScaler]:
    checkpoint = load_checkpoint(path)
    cfg = PatronConfig.model_validate(checkpoint["config"])
    if (cfg.sequence_length, cfg.horizon, cfg.feature_count) != (
        expected.sequence_length,
        expected.horizon,
        expected.feature_count,
    ):
        raise SystemExit(f"{path} has an incompatible input/horizon contract")
    model = build_model(cfg)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()
    return model, RobustFeatureScaler.load_from_dict(checkpoint["scaler"])


def _predict(
    model: Any,
    scaler: RobustFeatureScaler,
    frame: pd.DataFrame,
    positions: np.ndarray,
    sequence_length: int,
    batch_size: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    scaled = scaler.transform(frame[list(FEATURE_ORDER)].to_numpy(dtype=np.float64))
    windows = np.stack(
        [scaled[end - sequence_length + 1 : end + 1] for end in positions]
    ).astype(np.float32)
    chunks: list[np.ndarray] = []
    with torch.no_grad():
        for start in range(0, len(windows), batch_size):
            out = model(torch.from_numpy(windows[start : start + batch_size]))
            chunks.append(out["quantile"].numpy())
    quantiles = np.concatenate(chunks, axis=0)
    return quantiles[:, :, :, 0], quantiles[:, :, :, 1], quantiles[:, :, :, 2]


def _quantile_loss(pred: np.ndarray, target: np.ndarray, q: float) -> float:
    error = target - pred
    return float(np.mean(np.maximum(q * error, (q - 1.0) * error)))


def _directional_accuracy(
    pred_return: np.ndarray, actual_return: np.ndarray
) -> dict[str, float | int]:
    mask = np.abs(actual_return) > 1e-4
    if mask.sum() == 0:
        return {"all": float("nan"), "non_neutral": float("nan"), "n_non_neutral": 0}
    return {
        "all": float(np.mean(np.sign(pred_return) == np.sign(actual_return))),
        "non_neutral": float(
            np.mean(np.sign(pred_return[mask]) == np.sign(actual_return[mask]))
        ),
        "n_non_neutral": int(mask.sum()),
    }


def _summarise(
    pred: np.ndarray, actual: np.ndarray, q10: np.ndarray, q90: np.ndarray
) -> dict[str, Any]:
    """Replicate PATRON's audit metrics for [N, H, 3] relative values."""

    output: dict[str, Any] = {}
    for field_index, field in enumerate(("high", "low", "close")):
        p = pred[:, :, field_index]
        a = actual[:, :, field_index]
        error = a - p
        output[field] = {
            "mae_bps": float(np.mean(np.abs(error)) * 10_000),
            "rmse_bps": float(np.sqrt(np.mean(error**2)) * 10_000),
            "bias_bps": float(np.mean(error) * 10_000),
            "correlation": float(np.corrcoef(p.ravel(), a.ravel())[0, 1])
            if np.std(p) > 0 and np.std(a) > 0
            else 0.0,
        }
    close = output["close"]
    close.update(_directional_accuracy(pred[:, :, 2], actual[:, :, 2]))
    q10_close, q50, q90_close = q10[:, :, 2], pred[:, :, 2], q90[:, :, 2]
    target = actual[:, :, 2]
    close["pinball_q10"] = _quantile_loss(q10_close, target, 0.1)
    close["pinball_q50"] = _quantile_loss(q50, target, 0.5)
    close["pinball_q90"] = _quantile_loss(q90_close, target, 0.9)
    close["pinball_mean"] = (
        close["pinball_q10"] + close["pinball_q50"] + close["pinball_q90"]
    ) / 3.0
    close["coverage_80"] = float(np.mean((target >= q10_close) & (target <= q90_close)))
    close["mean_interval_width_bps"] = float(
        np.mean(q90_close - q10_close) * 10_000
    )
    close["predicted_std_bps"] = float(np.std(q50) * 10_000)
    close["actual_std_bps"] = float(np.std(target) * 10_000)
    return output


def _make_dataset(
    cfg: PatronConfig, frame: pd.DataFrame, candles: pd.DataFrame
) -> tuple[np.ndarray, np.ndarray]:
    """Return (target [N,H,3], bar positions) using PATRON's label semantics."""

    horizon = cfg.horizon
    sequence = cfg.sequence_length
    close = candles["close"].to_numpy(dtype=np.float64)
    high = candles["high"].to_numpy(dtype=np.float64)
    low = candles["low"].to_numpy(dtype=np.float64)
    count = len(frame)
    targets = np.full((count, horizon, 3), np.nan, dtype=np.float64)
    for step in range(1, horizon + 1):
        valid = np.arange(count) + step < count
        future = np.minimum(np.arange(count) + step, count - 1)
        targets[valid, step - 1, 0] = high[future][valid] / close[valid] - 1.0
        targets[valid, step - 1, 1] = low[future][valid] / close[valid] - 1.0
        targets[valid, step - 1, 2] = close[future][valid] / close[valid] - 1.0
    valid = frame["feature_valid"].to_numpy(dtype=bool) & np.isfinite(targets).all(
        axis=(1, 2)
    )
    positions = np.flatnonzero(valid)
    positions = positions[positions >= sequence - 1]
    return targets, positions


def _close_block(
    q10: np.ndarray, q50: np.ndarray, q90: np.ndarray, realised: np.ndarray
) -> dict[str, Any]:
    summary = _summarise(q50, realised, q10, q90)
    close = summary["close"]
    return {
        "close_mae_bps": close["mae_bps"],
        "close_rmse_bps": close["rmse_bps"],
        "close_bias_bps": close["bias_bps"],
        "high_mae_bps": summary["high"]["mae_bps"],
        "low_mae_bps": summary["low"]["mae_bps"],
        "directional_accuracy": close["all"],
        "directional_accuracy_non_neutral": close["non_neutral"],
        "directional_n_non_neutral": close["n_non_neutral"],
        "pinball_mean": close["pinball_mean"],
        "coverage_80": close["coverage_80"],
        "mean_interval_width_bps": close["mean_interval_width_bps"],
        "predicted_std_bps": close["predicted_std_bps"],
    }


def _baseline_block(
    close_realised: np.ndarray, previous_return: np.ndarray, drift: np.ndarray
) -> dict[str, Any]:
    persistence_error = np.abs(close_realised)
    previous_error = np.abs(close_realised - previous_return)
    drift_error = np.abs(close_realised - drift)
    return {
        "persistence_mae_bps": float(np.mean(persistence_error) * 10_000),
        "previous_candle_mae_bps": float(np.mean(previous_error) * 10_000),
        "rolling_mean_96_mae_bps": float(np.mean(drift_error) * 10_000),
    }


def _regime_slices(
    model_predictions: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]],
    realised: np.ndarray,
    frame: pd.DataFrame,
    positions: np.ndarray,
) -> dict[str, Any]:
    labelled = add_regimes(frame)
    output: dict[str, Any] = {}
    for regime_column in ("regime_trend", "regime_vol"):
        series = labelled[regime_column].to_numpy()[positions]
        breakdown: dict[str, Any] = {}
        for regime in pd.unique(series):
            mask = series == regime
            if int(mask.sum()) < 100:
                continue
            entry: dict[str, Any] = {"n": int(mask.sum())}
            entry["persistence_mae_bps"] = float(
                np.mean(np.abs(realised[mask, :, 2])) * 10_000
            )
            for name, (q10, q50, q90) in model_predictions.items():
                close = _summarise(
                    q50[mask], realised[mask], q10[mask], q90[mask]
                )["close"]
                entry[name] = {
                    "close_mae_bps": close["mae_bps"],
                    "directional_accuracy": close["all"],
                    "coverage_80": close["coverage_80"],
                }
            breakdown[str(regime)] = entry
        output[regime_column] = breakdown
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data/patron/BTCUSDT_15m.parquet")
    parser.add_argument("--candidate", default="models/patron/best.pt")
    parser.add_argument("--champion", default="models/patron/CHAMPION_V1_ROLLBACK.pt")
    parser.add_argument("--out", default="../docs/AI_TRADING_UPGRADE/PATRON_ROLLING_STABILITY.json")
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--threads", type=int, default=6)
    args = parser.parse_args()

    torch.set_num_threads(max(1, args.threads))
    data_path = Path(args.data)
    candidate_path = Path(args.candidate)
    champion_path = Path(args.champion)
    for path in (data_path, candidate_path, champion_path):
        if not path.exists():
            raise SystemExit(f"missing input: {path}")

    started = time.perf_counter()
    candles = pd.read_parquet(data_path)
    candles["timestamp_open"] = pd.to_datetime(candles["timestamp_open"], utc=True)
    candles["timestamp_close"] = pd.to_datetime(candles["timestamp_close"], utc=True)

    candidate_ckpt = load_checkpoint(candidate_path)
    cfg = PatronConfig.model_validate(candidate_ckpt["config"])
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
    realised = targets[test_positions]
    close_realised = realised[:, :, 2]

    last_return = (
        frame["close"].to_numpy() / frame["close"].shift(1).to_numpy() - 1.0
    )[test_positions]
    previous_return = np.repeat(last_return[:, None], cfg.horizon, axis=1)
    returns = np.nan_to_num(frame["close"].pct_change().to_numpy())
    rolling_mean = (
        pd.Series(returns)
        .rolling(cfg.sequence_length, min_periods=cfg.sequence_length)
        .mean()
        .to_numpy()
    )
    drift = np.repeat(rolling_mean[test_positions][:, None], cfg.horizon, axis=1)

    models: dict[str, Any] = {}
    predictions: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for name, path in (("champion", champion_path), ("candidate", candidate_path)):
        model, scaler = _load_model(path, cfg)
        forward_started = time.perf_counter()
        q10, q50, q90 = _predict(
            model,
            scaler,
            frame,
            test_positions,
            cfg.sequence_length,
            args.batch_size,
        )
        forward_seconds = time.perf_counter() - forward_started
        predictions[name] = (q10, q50, q90)
        overall = _close_block(q10, q50, q90, realised)
        overall["persistence_mae_bps"] = float(
            np.mean(np.abs(close_realised)) * 10_000
        )
        by_step = {}
        for step in range(cfg.horizon):
            by_step[str(step + 1)] = _close_block(
                q10[:, step : step + 1],
                q50[:, step : step + 1],
                q90[:, step : step + 1],
                realised[:, step : step + 1],
            )
        models[name] = {
            "checkpoint": str(path.resolve()),
            "sha256": _sha256(path),
            "forward_seconds": round(forward_seconds, 2),
            "windows": int(len(test_positions)),
            "overall": overall,
            "by_step": by_step,
        }

    blocks = np.array_split(np.arange(len(test_positions)), args.folds)
    timestamps = pd.to_datetime(candles["timestamp_open"]).iloc[test_positions]
    folds: list[dict[str, Any]] = []
    for number, block in enumerate(blocks, start=1):
        row: dict[str, Any] = {
            "fold": number,
            "start": timestamps.iloc[block[0]].isoformat(),
            "end": timestamps.iloc[block[-1]].isoformat(),
            "n": int(len(block)),
            "baselines": _baseline_block(
                close_realised[block], previous_return[block], drift[block]
            ),
        }
        for name, (q10, q50, q90) in predictions.items():
            row[name] = _close_block(
                q10[block], q50[block], q90[block], realised[block]
            )
        folds.append(row)

    regime_slices = _regime_slices(predictions, realised, frame, test_positions)

    candidate_overall = models["candidate"]["overall"]
    champion_overall = models["champion"]["overall"]
    report = {
        "report_version": "patron-rolling-stability-1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "method": (
            "Fixed-checkpoint evaluation over chronological blocks of the untouched "
            "chronological test split. No fold-wise retraining: the approved candidate "
            "was already trained; each block is out-of-sample for both checkpoints."
        ),
        "data": {
            "file": str(data_path.resolve()),
            "sha256": _sha256(data_path),
            "rows": int(len(candles)),
            "start": candles["timestamp_open"].iloc[0].isoformat(),
            "end": candles["timestamp_open"].iloc[-1].isoformat(),
        },
        "split": {
            "train_windows": int(len(split.train)),
            "validation_windows": int(len(split.val)),
            "test_windows": int(len(split.test)),
            "test_windows_evaluated": int(len(test_positions)),
            "test_first_bar": candles["timestamp_open"].iloc[int(test_positions[0])].isoformat(),
            "test_last_bar": candles["timestamp_open"].iloc[int(test_positions[-1])].isoformat(),
            "purge_bars": cfg.validation.purge_bars,
            "embargo_bars": cfg.validation.embargo_bars,
        },
        "models": models,
        "folds": folds,
        "regimes": regime_slices,
        "comparison": {
            "candidate_minus_champion_close_mae_bps": round(
                candidate_overall["close_mae_bps"] - champion_overall["close_mae_bps"], 4
            ),
            "candidate_minus_persistence_mae_bps": round(
                candidate_overall["close_mae_bps"]
                - candidate_overall["persistence_mae_bps"],
                4,
            ),
            "candidate_directional_accuracy": candidate_overall["directional_accuracy"],
            "candidate_coverage_80": candidate_overall["coverage_80"],
            "note": (
                "A negative candidate-minus-persistence value would mean the candidate "
                "beats last-close persistence. Positive means it does not."
            ),
        },
        "limitations": [
            "Fixed checkpoints; no fold-wise retraining or multi-seed ensemble.",
            "One local dataset and one chronological test split.",
            "No fees, funding, slippage, fills or execution simulation.",
            "Rolling blocks test temporal stability, not a retrained walk-forward strategy.",
        ],
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "windows": len(test_positions),
                "champion": {
                    "close_mae_bps": champion_overall["close_mae_bps"],
                    "direction": champion_overall["directional_accuracy"],
                },
                "candidate": {
                    "close_mae_bps": candidate_overall["close_mae_bps"],
                    "direction": candidate_overall["directional_accuracy"],
                    "coverage_80": candidate_overall["coverage_80"],
                },
                "persistence_mae_bps": candidate_overall["persistence_mae_bps"],
            },
            indent=2,
        )
    )
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
