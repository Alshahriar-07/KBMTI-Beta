"""Leakage-safe PATRON predictive-edge research.

This script implements the pre-registered protocol in
``docs/AI_TRADING_UPGRADE/PATRON_PREDICTIVE_EDGE_PROTOCOL.md``:

* genuine expanding-window walk-forward training, four chronological folds;
* train-only feature scaling in every fold;
* purge/embargo gaps between train, validation and test;
* absolute PATRON and persistence-residual PATRON candidates;
* persistence, statistical drift, existing-checkpoint and residual comparisons;
* predefined trend-strength and volatility slices, per-horizon metrics and
  paired day-block bootstrap confidence intervals;
* promotion assessment against fixed criteria.

It never writes to ``backend/models/patron``. Fold checkpoints are written under
``backend/experiments`` only. Production inference is untouched.

Run from ``backend``::

    PYTHONPATH=. .venv/Scripts/python.exe scripts/patron_predictive_edge.py \
        --out ../docs/AI_TRADING_UPGRADE/PATRON_PREDICTIVE_EDGE_RESULTS.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import torch

from patron.config import PatronConfig
from patron.datasets.loader import PreparedData
from patron.datasets.windows import SequenceDataset, valid_window_positions
from patron.evaluation.regimes import add_regimes
from patron.features.scaler import RobustFeatureScaler
from patron.features.schema import FEATURE_ORDER
from patron.labels.range_labels import frame_to_targets
from patron.models.patron_net import build_model, count_parameters
from patron.training.trainer import load_checkpoint, train

PROTOCOL_VERSION = "patron-predictive-edge-1.0.0"
NEUTRAL_BAND = 1e-4
BOOTSTRAP_SEED = 20261123
FOLD_TEST_STARTS = (0.60, 0.70, 0.80, 0.90)
FOLD_TEST_FRACTION = 0.10
FOLD_VAL_FRACTION = 0.06
FOLD_GAP_WINDOWS = 24
MIN_REGIME_N = 100


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _make_targets(frame: pd.DataFrame, horizon: int) -> np.ndarray:
    """Reconstruct PATRON's [N, H, 3] targets from the built dataset columns."""
    return frame_to_targets(frame, horizon=horizon)


def _drift_matrix(candles: pd.DataFrame, horizon: int, lookback: int = 96) -> np.ndarray:
    close = candles["close"].to_numpy(dtype=np.float64)
    returns = np.zeros_like(close)
    returns[1:] = close[1:] / close[:-1] - 1.0
    mean_return = (
        pd.Series(returns)
        .rolling(lookback, min_periods=lookback)
        .mean()
        .to_numpy(dtype=np.float64)
    )
    mean_return = np.nan_to_num(mean_return, nan=0.0)
    drift = np.empty((len(close), horizon), dtype=np.float64)
    for step in range(1, horizon + 1):
        drift[:, step - 1] = np.power(1.0 + mean_return, step) - 1.0
    return drift


@dataclass
class FoldSplit:
    train_start: str
    train_end: str
    val_start: str
    val_end: str
    test_start: str
    test_end: str
    purge_bars: int
    embargo_bars: int

    def summary(self) -> dict[str, Any]:
        return {
            "train": {"start": self.train_start, "end": self.train_end},
            "val": {"start": self.val_start, "end": self.val_end},
            "test": {"start": self.test_start, "end": self.test_end},
            "purge_bars": self.purge_bars,
            "embargo_bars": self.embargo_bars,
        }


def _fold_boundaries(n: int) -> list[dict[str, int]]:
    folds = []
    for index, start_fraction in enumerate(FOLD_TEST_STARTS, start=1):
        test_start = int(math.floor(n * start_fraction))
        test_end = min(n, int(math.floor(n * (start_fraction + FOLD_TEST_FRACTION))))
        val_end = max(0, test_start - FOLD_GAP_WINDOWS)
        val_start = max(0, val_end - int(math.floor(n * FOLD_VAL_FRACTION)))
        train_end = max(0, val_start - FOLD_GAP_WINDOWS)
        if not (0 < train_end < val_start < val_end < test_start < test_end):
            raise SystemExit(f"fold {index} boundaries are invalid: {locals()}")
        folds.append(
            {
                "fold": index,
                "train_end": train_end,
                "val_start": val_start,
                "val_end": val_end,
                "test_start": test_start,
                "test_end": test_end,
            }
        )
    return folds


def _split_dates(
    frame: pd.DataFrame, positions: np.ndarray, start: int, end: int
) -> tuple[str, str, int]:
    bars = positions[start:end]
    stamps = pd.to_datetime(frame["timestamp_open"].iloc[bars], utc=True)
    return stamps.iloc[0].isoformat(), stamps.iloc[-1].isoformat(), len(bars)


def _initialise_forecast_head(model: torch.nn.Module, half_width: float = 0.002) -> None:
    head = model.quantile_head
    with torch.no_grad():
        head.weight.normal_(mean=0.0, std=0.01)
        head.bias.zero_()
        bias = head.bias.view(model.horizon, model.n_range_fields, model.n_quantiles)
        spread = math.log(math.expm1(max(half_width, 1e-5)))
        bias[:, :, 1].fill_(spread)
        bias[:, :, 2].fill_(spread)


def _predict(
    model: torch.nn.Module,
    scaled_features: np.ndarray,
    positions: np.ndarray,
    sequence_length: int,
    batch_size: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    windows = np.stack(
        [
            scaled_features[end - sequence_length + 1 : end + 1]
            for end in positions
        ]
    ).astype(np.float32)
    chunks: list[np.ndarray] = []
    with torch.no_grad():
        for start in range(0, len(windows), batch_size):
            out = model(torch.from_numpy(windows[start : start + batch_size]))
            chunks.append(out["quantile"].numpy())
    quantiles = np.concatenate(chunks, axis=0)
    # Close path only: [N, horizon]. The high/low fields are not used here.
    return (
        quantiles[:, :, 2, 0],
        quantiles[:, :, 2, 1],
        quantiles[:, :, 2, 2],
    )


def _pinball(pred: np.ndarray, target: np.ndarray, q: float) -> float:
    error = target - pred
    return float(np.mean(np.maximum(q * error, (q - 1.0) * error)))


def _balanced_accuracy(pred: np.ndarray, actual: np.ndarray) -> float:
    valid = np.abs(actual) > NEUTRAL_BAND
    if not valid.any():
        return float("nan")
    predicted_up = pred > 0
    actual_up = actual > 0
    recalls = []
    for target in (False, True):
        mask = valid & (actual_up == target)
        if mask.sum() == 0:
            continue
        recalls.append(float(np.mean(predicted_up[mask] == target)))
    return float(np.mean(recalls)) if len(recalls) == 2 else float("nan")


def _classification_direction(pred: np.ndarray, actual: np.ndarray) -> dict[str, Any]:
    valid = np.abs(actual) > NEUTRAL_BAND
    predicted_up = pred > 0
    actual_up = actual > 0
    tp = int(np.sum(valid & predicted_up & actual_up))
    tn = int(np.sum(valid & ~predicted_up & ~actual_up))
    fp = int(np.sum(valid & predicted_up & ~actual_up))
    fn = int(np.sum(valid & ~predicted_up & actual_up))
    recall_up = tp / (tp + fn) if (tp + fn) else 0.0
    recall_down = tn / (tn + fp) if (tn + fp) else 0.0
    precision_up = tp / (tp + fp) if (tp + fp) else 0.0
    precision_down = tn / (tn + fn) if (tn + fn) else 0.0
    return {
        "balanced_accuracy": float((recall_up + recall_down) / 2.0)
        if (tp + fn) and (tn + fp)
        else float("nan"),
        "precision_up": precision_up,
        "recall_up": recall_up,
        "precision_down": precision_down,
        "recall_down": recall_down,
        "n_non_neutral": int(valid.sum()),
        "predicted_up_rate": float(np.mean(predicted_up[valid])) if valid.any() else float("nan"),
        "actual_up_rate": float(np.mean(actual_up[valid])) if valid.any() else float("nan"),
    }


def _metrics(
    q10: np.ndarray, q50: np.ndarray, q90: np.ndarray, actual: np.ndarray
) -> dict[str, Any]:
    error = actual - q50
    absolute = np.abs(error)
    summary = {
        "n": int(actual.size),
        "close_mae_bps": float(np.mean(absolute) * 10_000),
        "close_rmse_bps": float(np.sqrt(np.mean(error**2)) * 10_000),
        "close_bias_bps": float(np.mean(error) * 10_000),
        "return_mae_bps": float(np.mean(absolute) * 10_000),
        "directional_accuracy_all": float(np.mean(np.sign(q50) == np.sign(actual))),
        "directional_accuracy_non_neutral": float(
            np.mean(np.sign(q50[abs(actual) > NEUTRAL_BAND]) == np.sign(actual[abs(actual) > NEUTRAL_BAND]))
        )
        if np.any(np.abs(actual) > NEUTRAL_BAND)
        else float("nan"),
        "pinball_q10": _pinball(q10, actual, 0.1),
        "pinball_q50": _pinball(q50, actual, 0.5),
        "pinball_q90": _pinball(q90, actual, 0.9),
        "coverage_80": float(np.mean((actual >= q10) & (actual <= q90))),
        "mean_interval_width_bps": float(np.mean(q90 - q10) * 10_000),
        "predicted_std_bps": float(np.std(q50) * 10_000),
        "actual_std_bps": float(np.std(actual) * 10_000),
    }
    summary["pinball_mean"] = (
        summary["pinball_q10"] + summary["pinball_q50"] + summary["pinball_q90"]
    ) / 3.0
    summary.update(_classification_direction(q50, actual))
    return summary


def _trend_labels(frame: pd.DataFrame, positions: np.ndarray) -> np.ndarray:
    atr_pct = frame["atr14_pct"].to_numpy(dtype=np.float64)[positions]
    gap9 = frame["ema9_gap"].to_numpy(dtype=np.float64)[positions]
    gap21 = frame["ema21_gap"].to_numpy(dtype=np.float64)[positions]
    with np.errstate(divide="ignore", invalid="ignore"):
        norm9 = np.where(atr_pct > 0, gap9 / atr_pct, 0.0)
        norm21 = np.where(atr_pct > 0, gap21 / atr_pct, 0.0)
    score = (norm9 + norm21) / 2.0
    labels = np.full(len(positions), "sideways", dtype=object)
    strong_bull = (score >= 0.75) & (norm9 > 0) & (norm21 > 0)
    weak_bull = (score > 0.25) & ~strong_bull
    strong_bear = (score <= -0.75) & (norm9 < 0) & (norm21 < 0)
    weak_bear = (score < -0.25) & ~strong_bear
    labels[weak_bull] = "weak_bullish"
    labels[strong_bull] = "strong_bullish"
    labels[weak_bear] = "weak_bearish"
    labels[strong_bear] = "strong_bearish"
    return labels


def _regime_labels(
    frame: pd.DataFrame, positions: np.ndarray
) -> dict[str, np.ndarray]:
    labelled = add_regimes(frame)
    return {
        "trend_strength": _trend_labels(frame, positions),
        "volatility": labelled["regime_vol"].to_numpy()[positions],
    }


def _regime_slices(
    predictions: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]],
    actual: np.ndarray,
    regimes: dict[str, np.ndarray],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for family, labels in regimes.items():
        slices: dict[str, Any] = {}
        for label in pd.unique(labels):
            mask = labels == label
            entry: dict[str, Any] = {
                "n": int(mask.sum()),
                "low_sample": bool(mask.sum() < MIN_REGIME_N),
            }
            for name, (q10, q50, q90) in predictions.items():
                entry[name] = _metrics(q10[mask], q50[mask], q90[mask], actual[mask])
            slices[str(label)] = entry
        output[family] = slices
    return output


def _training_config(base: PatronConfig, epochs: int, patience: int) -> PatronConfig:
    training = base.training.model_copy(
        update={"max_epochs": epochs, "early_stopping_patience": patience}
    )
    return base.model_copy(update={"training": training})


def _build_prepared_data(
    frame: pd.DataFrame,
    scaler: RobustFeatureScaler,
    scaled: np.ndarray,
    positions: np.ndarray,
    train_positions: np.ndarray,
    val_positions: np.ndarray,
    test_positions: np.ndarray,
    cfg: PatronConfig,
    split: FoldSplit,
    stride: int,
) -> PreparedData:
    train_ds = SequenceDataset(
        scaled,
        frame,
        train_positions[::stride],
        cfg.sequence_length,
        cfg.horizon,
    )
    val_ds = SequenceDataset(scaled, frame, val_positions, cfg.sequence_length, cfg.horizon)
    test_ds = SequenceDataset(scaled, frame, test_positions, cfg.sequence_length, cfg.horizon)
    bundles = SimpleNamespace(
        train=train_ds,
        val=val_ds,
        test=test_ds,
        split=split,
        positions=positions,
    )
    return PreparedData(
        frame=frame,
        scaler=scaler,
        scaled_features=scaled,
        bundles=bundles,  # type: ignore[arg-type]
    )


def _train_candidate(
    frame: pd.DataFrame,
    scaler: RobustFeatureScaler,
    scaled: np.ndarray,
    positions: np.ndarray,
    train_positions: np.ndarray,
    val_positions: np.ndarray,
    test_positions: np.ndarray,
    split: FoldSplit,
    cfg: PatronConfig,
    fold: int,
    kind: str,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], dict[str, Any]]:
    fold_cfg = _training_config(cfg, args.epochs, args.patience)
    data = _build_prepared_data(
        frame,
        scaler,
        scaled,
        positions,
        train_positions,
        val_positions,
        test_positions,
        fold_cfg,
        split,
        args.train_stride,
    )
    model = build_model(fold_cfg)
    _initialise_forecast_head(model)
    started = time.perf_counter()
    history = train(
        model,
        data,
        fold_cfg,
        run_name=f"kbmti_edge_f{fold}_{kind}",
        max_epochs=args.epochs,
        batch_size=args.batch_size,
        num_threads=args.threads,
        seed=args.seed,
    )
    elapsed = time.perf_counter() - started
    if history.best_epoch < 0 or history.run_dir is None:
        raise SystemExit(f"fold {fold} {kind} produced no checkpoint")
    checkpoint = load_checkpoint(history.run_dir / "best.pt")
    best_model = build_model(fold_cfg)
    best_model.load_state_dict(checkpoint["model_state"])
    best_model.eval()
    metadata = {
        "kind": kind,
        "run_dir": str(history.run_dir),
        "parameters": count_parameters(best_model),
        "epochs_run": len(history.records),
        "best_epoch": history.best_epoch,
        "best_val_loss": history.best_val_loss,
        "stopped_early": history.stopped_early,
        "elapsed_seconds": round(elapsed, 2),
        "train_windows": len(data.bundles.train),
        "val_windows": len(data.bundles.val),
        "test_windows": len(data.bundles.test),
        "seed": args.seed,
        "train_stride": args.train_stride,
        "checkpoint_sha256": _sha256(history.run_dir / "best.pt"),
    }
    return {"model": best_model, "history": history}, metadata


def _quantile_baselines(
    targets: np.ndarray, drift: np.ndarray, positions: np.ndarray
) -> dict[str, np.ndarray]:
    actual = targets[positions][:, :, 2]
    drift_values = drift[positions]
    persistence_residual = actual
    drift_residual = actual - drift_values
    q = (0.1, 0.5, 0.9)
    persistence_q = np.stack(
        [np.quantile(persistence_residual[:, step], q) for step in range(actual.shape[1])],
        axis=1,
    )
    drift_q = np.stack(
        [np.quantile(drift_residual[:, step], q) for step in range(actual.shape[1])],
        axis=1,
    )
    return {
        "persistence_q10": persistence_q[0],
        "persistence_q50": persistence_q[1],
        "persistence_q90": persistence_q[2],
        "drift_q10": drift_q[0],
        "drift_q50": drift_q[1],
        "drift_q90": drift_q[2],
    }


def _flat_day_groups(timestamps: pd.Series, horizon: int) -> list[np.ndarray]:
    dates = pd.to_datetime(timestamps, utc=True).dt.floor("D").to_numpy()
    _, inverse = np.unique(dates, return_inverse=True)
    groups = []
    for day in range(int(inverse.max()) + 1):
        windows = np.flatnonzero(inverse == day)
        if len(windows) == 0:
            continue
        flat = (windows[:, None] * horizon + np.arange(horizon)[None, :]).ravel()
        groups.append(flat)
    return groups


def _window_day_groups(timestamps: pd.Series) -> list[np.ndarray]:
    dates = pd.to_datetime(timestamps, utc=True).dt.floor("D").to_numpy()
    _, inverse = np.unique(dates, return_inverse=True)
    return [
        np.flatnonzero(inverse == day)
        for day in range(int(inverse.max()) + 1)
        if np.any(inverse == day)
    ]


def _bootstrap_mae_diff(
    groups: list[np.ndarray],
    candidate_error: np.ndarray,
    baseline_error: np.ndarray,
    reps: int,
    seed: int,
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    n_groups = len(groups)
    draws = np.empty(reps, dtype=np.float64)
    for index in range(reps):
        chosen = rng.integers(0, n_groups, n_groups)
        flat = np.concatenate([groups[item] for item in chosen])
        draws[index] = float(
            np.mean(candidate_error[flat]) - np.mean(baseline_error[flat])
        )
    return {
        "point_diff_bps": float(
            np.mean(candidate_error) - np.mean(baseline_error)
        )
        * 10_000,
        "ci95_bps": [
            float(np.percentile(draws, 2.5) * 10_000),
            float(np.percentile(draws, 97.5) * 10_000),
        ],
        "ci975_bps": [
            float(np.percentile(draws, 1.25) * 10_000),
            float(np.percentile(draws, 98.75) * 10_000),
        ],
    }


def _bootstrap_balanced_accuracy(
    groups: list[np.ndarray],
    pred: np.ndarray,
    actual: np.ndarray,
    reps: int,
    seed: int,
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    n_groups = len(groups)
    draws = np.empty(reps, dtype=np.float64)
    for index in range(reps):
        chosen = rng.integers(0, n_groups, n_groups)
        flat = np.concatenate([groups[item] for item in chosen])
        draws[index] = _balanced_accuracy(pred[flat], actual[flat])
    return {
        "point": _balanced_accuracy(pred, actual),
        "ci95": [
            float(np.nanpercentile(draws, 2.5)),
            float(np.nanpercentile(draws, 97.5)),
        ],
        "ci975": [
            float(np.nanpercentile(draws, 1.25)),
            float(np.nanpercentile(draws, 98.75)),
        ],
    }


def _assess_candidate(
    name: str,
    metrics: dict[str, Any],
    folds: list[dict[str, Any]],
    bootstrap: dict[str, Any],
    baseline_metrics: dict[str, Any],
    residual: bool,
) -> dict[str, Any]:
    point = bootstrap["mae_vs_persistence"]["point_diff_bps"]
    upper = bootstrap["mae_vs_persistence"]["ci975_bps"][1]
    fold_consistency = sum(
        1
        for fold in folds
        if fold["metrics"][name]["close_mae_bps"]
        < fold["metrics"]["persistence"]["close_mae_bps"]
    )
    fold_coverage = [fold["metrics"][name]["coverage_80"] for fold in folds]
    direction = bootstrap["balanced_accuracy"]
    checks = {
        "mae_improvement_min_0_50_bp": point <= -0.50,
        "mae_ci975_upper_below_zero": upper < 0.0,
        "fold_consistency_at_least_3_of_4": fold_consistency >= 3,
        "balanced_accuracy_at_least_0_50": metrics["balanced_accuracy"] >= 0.50,
        "balanced_accuracy_ci975_lower_above_0_50": direction["ci975"][0] > 0.50,
        "coverage_pooled_0_75_to_0_85": 0.75 <= metrics["coverage_80"] <= 0.85,
        "coverage_each_fold_0_70_to_0_90": all(
            0.70 <= value <= 0.90 for value in fold_coverage
        ),
        "rmse_not_worse_than_persistence": metrics["close_rmse_bps"]
        <= baseline_metrics["close_rmse_bps"],
        "pinball_not_worse_than_persistence": metrics["pinball_mean"]
        <= baseline_metrics["pinball_mean"],
    }
    if residual:
        checks["residual_improvement_vs_drift_min_0_25_bp"] = (
            bootstrap["mae_vs_drift"]["point_diff_bps"] <= -0.25
            and bootstrap["mae_vs_drift"]["ci975_bps"][1] < 0.0
        )
    failed = [key for key, value in checks.items() if not value]
    return {
        "candidate": name,
        "eligible": not failed,
        "checks": checks,
        "failed_checks": failed,
        "fold_consistency": f"{fold_consistency}/4",
        "fold_coverage_80": fold_coverage,
        "mae_vs_persistence": bootstrap["mae_vs_persistence"],
        "mae_vs_drift": bootstrap.get("mae_vs_drift"),
        "balanced_accuracy": direction,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="../PATRON/data/features/BTCUSDT_dataset.parquet")
    parser.add_argument("--config", default="../PATRON/configs/candidate_v2.yaml")
    parser.add_argument("--checkpoint", default="models/patron/best.pt")
    parser.add_argument(
        "--out", default="../docs/AI_TRADING_UPGRADE/PATRON_PREDICTIVE_EDGE_RESULTS.json"
    )
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--patience", type=int, default=3)
    parser.add_argument("--train-stride", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--fold-limit", type=int, default=0, help="debug only")
    args = parser.parse_args()

    torch.set_num_threads(max(1, args.threads))
    started = time.perf_counter()
    data_path = Path(args.data).resolve()
    config_path = Path(args.config).resolve()
    checkpoint_path = Path(args.checkpoint).resolve()
    for path in (data_path, config_path, checkpoint_path):
        if not path.exists():
            raise SystemExit(f"missing input: {path}")

    cfg = PatronConfig.load(config_path)
    candles = pd.read_parquet(data_path)
    candles["timestamp_open"] = pd.to_datetime(candles["timestamp_open"], utc=True)
    candles["timestamp_close"] = pd.to_datetime(candles["timestamp_close"], utc=True)
    candles = candles.sort_values("timestamp_open").reset_index(drop=True)

    targets = _make_targets(candles, cfg.horizon)
    positions = valid_window_positions(
        candles,
        seq_len=cfg.sequence_length,
        horizon=cfg.horizon,
        stride=1,
    ).positions
    drift = _drift_matrix(candles, cfg.horizon)
    regimes = _regime_labels(candles, positions)

    fold_plans = _fold_boundaries(len(positions))
    if args.fold_limit:
        fold_plans = fold_plans[: args.fold_limit]

    deployed_checkpoint = load_checkpoint(checkpoint_path)
    deployed_cfg = PatronConfig.model_validate(deployed_checkpoint["config"])
    deployed_model = build_model(deployed_cfg)
    deployed_model.load_state_dict(deployed_checkpoint["model_state"])
    deployed_model.eval()
    deployed_scaler = RobustFeatureScaler.load_from_dict(deployed_checkpoint["scaler"])
    deployed_scaled = deployed_scaler.transform_frame(candles)

    folds: list[dict[str, Any]] = []
    pooled: dict[str, dict[str, list[np.ndarray]]] = {}
    pooled_actual: list[np.ndarray] = []
    pooled_timestamps: list[pd.Series] = []
    pooled_regime: dict[str, list[np.ndarray]] = {"trend_strength": [], "volatility": []}

    for plan in fold_plans:
        fold = plan["fold"]
        train_positions = positions[: plan["train_end"]]
        val_positions = positions[plan["val_start"] : plan["val_end"]]
        test_positions = positions[plan["test_start"] : plan["test_end"]]
        if not (
            train_positions[-1] < val_positions[0] < val_positions[-1] < test_positions[0]
        ):
            raise SystemExit(f"fold {fold} position ordering failed")
        train_start, train_end_date, train_n = _split_dates(
            candles, positions, 0, plan["train_end"]
        )
        val_start, val_end_date, val_n = _split_dates(
            candles, positions, plan["val_start"], plan["val_end"]
        )
        test_start, test_end_date, test_n = _split_dates(
            candles, positions, plan["test_start"], plan["test_end"]
        )
        if train_positions[-1] >= test_positions[0]:
            raise SystemExit(f"fold {fold} leakage guard failed")
        split = FoldSplit(
            train_start,
            train_end_date,
            val_start,
            val_end_date,
            test_start,
            test_end_date,
            purge_bars=cfg.validation.purge_bars,
            embargo_bars=cfg.validation.embargo_bars,
        )

        fit_end_bar = int(train_positions[-1])
        fit_rows = candles.iloc[: fit_end_bar + 1]
        fit_rows = fit_rows[fit_rows["feature_valid"].to_numpy(dtype=bool)]
        scaler = RobustFeatureScaler.fit(
            fit_rows[list(FEATURE_ORDER)].to_numpy(dtype=np.float64),
            metadata={
                "fold": fold,
                "fit_end_bar": fit_end_bar,
                "fit_rows": int(len(fit_rows)),
                "fit_end_timestamp": candles["timestamp_open"].iloc[fit_end_bar].isoformat(),
            },
        )
        scaled = scaler.transform_frame(candles)
        if fit_end_bar >= int(test_positions[0]):
            raise SystemExit(f"fold {fold} scaler leakage guard failed")

        quantile_base = _quantile_baselines(targets, drift, train_positions)
        actual = targets[test_positions]
        actual_close = actual[:, :, 2]
        drift_test = drift[test_positions]

        candidates: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        training_metadata: dict[str, Any] = {}

        absolute, absolute_meta = _train_candidate(
            candles,
            scaler,
            scaled,
            positions,
            train_positions,
            val_positions,
            test_positions,
            split,
            cfg,
            fold,
            "absolute",
            args,
        )
        training_metadata["absolute"] = absolute_meta
        a10, a50, a90 = _predict(
            absolute["model"],
            scaled,
            test_positions,
            cfg.sequence_length,
            args.batch_size,
        )
        candidates["patron_absolute"] = (a10, a50, a90)

        frame_residual = candles.copy()
        for step in range(1, cfg.horizon + 1):
            frame_residual[f"tgt_close_{step}"] = (
                frame_residual[f"tgt_close_{step}"].to_numpy(dtype=np.float64)
                - drift[:, step - 1]
            )
        residual, residual_meta = _train_candidate(
            frame_residual,
            scaler,
            scaled,
            positions,
            train_positions,
            val_positions,
            test_positions,
            split,
            cfg,
            fold,
            "residual",
            args,
        )
        training_metadata["residual"] = residual_meta
        r10, r50, r90 = _predict(
            residual["model"],
            scaled,
            test_positions,
            cfg.sequence_length,
            args.batch_size,
        )
        candidates["patron_residual"] = (
            r10 + drift_test,
            r50 + drift_test,
            r90 + drift_test,
        )

        n_test = len(test_positions)
        candidates["persistence"] = (
            np.tile(quantile_base["persistence_q10"], (n_test, 1)),
            np.tile(quantile_base["persistence_q50"], (n_test, 1)),
            np.tile(quantile_base["persistence_q90"], (n_test, 1)),
        )
        candidates["statistical_drift"] = (
            drift_test + quantile_base["drift_q10"],
            drift_test + quantile_base["drift_q50"],
            drift_test + quantile_base["drift_q90"],
        )

        d10, d50, d90 = _predict(
            deployed_model,
            deployed_scaled,
            test_positions,
            deployed_cfg.sequence_length,
            args.batch_size,
        )
        candidates["deployed_patron"] = (d10, d50, d90)

        fold_metrics = {
            name: _metrics(q10, q50, q90, actual_close)
            for name, (q10, q50, q90) in candidates.items()
        }
        fold_regimes = {
            "trend_strength": regimes["trend_strength"][
                plan["test_start"] : plan["test_end"]
            ],
            "volatility": regimes["volatility"][
                plan["test_start"] : plan["test_end"]
            ],
        }
        by_step: dict[str, Any] = {}
        for step in range(cfg.horizon):
            by_step[str(step + 1)] = {
                name: _metrics(
                    q10[:, step : step + 1],
                    q50[:, step : step + 1],
                    q90[:, step : step + 1],
                    actual_close[:, step : step + 1],
                )
                for name, (q10, q50, q90) in candidates.items()
            }
        fold_report = {
            "fold": fold,
            "boundaries": {
                "train": [train_start, train_end_date, train_n],
                "validation": [val_start, val_end_date, val_n],
                "test": [test_start, test_end_date, test_n],
                "gap_windows": FOLD_GAP_WINDOWS,
                "purge_bars": cfg.validation.purge_bars,
                "embargo_bars": cfg.validation.embargo_bars,
            },
            "scaler_fit": {
                "fit_end_bar": fit_end_bar,
                "fit_rows": int(len(fit_rows)),
                "fit_end_timestamp": candles["timestamp_open"].iloc[fit_end_bar].isoformat(),
                "median": scaler.median.tolist(),
                "scale": scaler.scale.tolist(),
            },
            "training": training_metadata,
            "metrics": fold_metrics,
            "by_step": by_step,
            "by_regime": _regime_slices(candidates, actual_close, fold_regimes),
            "leakage_checks": {
                "train_last_bar": int(train_positions[-1]),
                "val_first_bar": int(val_positions[0]),
                "val_last_bar": int(val_positions[-1]),
                "test_first_bar": int(test_positions[0]),
                "ordering_ok": bool(
                    train_positions[-1] < val_positions[0] < val_positions[-1] < test_positions[0]
                ),
                "scaler_fit_ends_before_test": bool(fit_end_bar < test_positions[0]),
            },
        }
        folds.append(fold_report)

        pooled_actual.append(actual_close)
        pooled_timestamps.append(
            pd.Series(pd.to_datetime(candles["timestamp_open"].iloc[test_positions], utc=True))
        )
        for family, labels in fold_regimes.items():
            pooled_regime[family].append(labels)
        for name, (q10, q50, q90) in candidates.items():
            entry = pooled.setdefault(
                name, {"q10": [], "q50": [], "q90": [], "actual": []}
            )
            entry["q10"].append(q10)
            entry["q50"].append(q50)
            entry["q90"].append(q90)
            entry["actual"].append(actual_close)

    if not pooled["persistence"]["q10"]:
        raise SystemExit("no folds were evaluated")

    pooled_arrays = {
        name: (
            np.concatenate(entry["q10"]),
            np.concatenate(entry["q50"]),
            np.concatenate(entry["q90"]),
        )
        for name, entry in pooled.items()
    }
    pooled_actual_array = np.concatenate(pooled_actual)
    pooled_timestamp_series = pd.concat(pooled_timestamps, ignore_index=True)
    pooled_metrics = {
        name: _metrics(q10, q50, q90, pooled_actual_array)
        for name, (q10, q50, q90) in pooled_arrays.items()
    }
    pooled_regimes = {
        family: np.concatenate(values) for family, values in pooled_regime.items()
    }
    pooled_by_regime = _regime_slices(
        pooled_arrays, pooled_actual_array, pooled_regimes
    )
    pooled_by_step = {
        str(step + 1): {
            name: _metrics(
                q10[:, step : step + 1],
                q50[:, step : step + 1],
                q90[:, step : step + 1],
                pooled_actual_array[:, step : step + 1],
            )
            for name, (q10, q50, q90) in pooled_arrays.items()
        }
        for step in range(cfg.horizon)
    }

    flat_groups = _flat_day_groups(pooled_timestamp_series, cfg.horizon)
    window_groups = _window_day_groups(pooled_timestamp_series)
    candidate_bootstrap: dict[str, Any] = {}
    for candidate, _residual in (("patron_absolute", False), ("patron_residual", True)):
        q10, q50, q90 = pooled_arrays[candidate]
        candidate_error = np.abs(pooled_actual_array - q50).ravel()
        persistence_error = np.abs(
            pooled_actual_array - pooled_arrays["persistence"][1]
        ).ravel()
        drift_error = np.abs(
            pooled_actual_array - pooled_arrays["statistical_drift"][1]
        ).ravel()
        item = {
            "mae_vs_persistence": _bootstrap_mae_diff(
                flat_groups,
                candidate_error,
                persistence_error,
                args.bootstrap,
                BOOTSTRAP_SEED + (0 if candidate == "patron_absolute" else 1),
            ),
            "mae_vs_drift": _bootstrap_mae_diff(
                flat_groups,
                candidate_error,
                drift_error,
                args.bootstrap,
                BOOTSTRAP_SEED + (2 if candidate == "patron_absolute" else 3),
            ),
            "balanced_accuracy": _bootstrap_balanced_accuracy(
                window_groups,
                q50,
                pooled_actual_array,
                args.bootstrap,
                BOOTSTRAP_SEED + (4 if candidate == "patron_absolute" else 5),
            ),
        }
        candidate_bootstrap[candidate] = item

    assessments = {
        "patron_absolute": _assess_candidate(
            "patron_absolute",
            pooled_metrics["patron_absolute"],
            folds,
            candidate_bootstrap["patron_absolute"],
            pooled_metrics["persistence"],
            residual=False,
        ),
        "patron_residual": _assess_candidate(
            "patron_residual",
            pooled_metrics["patron_residual"],
            folds,
            candidate_bootstrap["patron_residual"],
            pooled_metrics["persistence"],
            residual=True,
        ),
    }
    eligible = [name for name, item in assessments.items() if item["eligible"]]
    overall_status = "PROMOTION_RECOMMENDED" if eligible else "NO_DEMONSTRATED_EDGE"
    recommended = (
        min(eligible, key=lambda name: pooled_metrics[name]["close_mae_bps"])
        if eligible
        else None
    )

    protocol_compliant = (
        len(fold_plans) == 4
        and args.epochs == 8
        and args.patience == 3
        and args.train_stride == 8
        and args.bootstrap == 2000
    )
    report = {
        "report_version": "patron-predictive-edge-results-1.0.0",
        "protocol_version": PROTOCOL_VERSION,
        "protocol_compliant": protocol_compliant,
        "generated_at": datetime.now(UTC).isoformat(),
        "method": (
            "Expanding-window chronological walk-forward with per-fold train-only "
            "scaling, 24-window purge/embargo gaps, absolute and persistence-residual "
            "PATRON candidates, and paired day-block bootstrap inference."
        ),
        "data": {
            "file": str(data_path),
            "sha256": _sha256(data_path),
            "rows": int(len(candles)),
            "start": candles["timestamp_open"].iloc[0].isoformat(),
            "end": candles["timestamp_open"].iloc[-1].isoformat(),
            "valid_windows": int(len(positions)),
        },
        "protocol_sha256": _sha256(
            Path("../docs/AI_TRADING_UPGRADE/PATRON_PREDICTIVE_EDGE_PROTOCOL.md")
        )
        if Path("../docs/AI_TRADING_UPGRADE/PATRON_PREDICTIVE_EDGE_PROTOCOL.md").exists()
        else None,
        "folds": folds,
        "pooled": {
            "metrics": pooled_metrics,
            "by_step": pooled_by_step,
            "by_regime": pooled_by_regime,
            "bootstrap": candidate_bootstrap,
        },
        "assessments": assessments,
        "decision": {
            "status": overall_status,
            "recommended_candidate": recommended,
            "production_model_changed": False,
            "production_model": str(checkpoint_path),
            "note": (
                "A recommendation is not deployment. The current production checkpoint "
                "was not copied or modified; any promotion requires separate human approval."
            ),
        },
        "limitations": [
            "One local BTCUSDT M15 dataset; no live broker sample.",
            "Four folds, one seed; bootstrap intervals account for sampling but not model-seed variance.",
            "No fees, funding, slippage, fills or execution simulation.",
            "The deployed checkpoint reference is not leakage-safe across folds and is excluded from promotion.",
            "Regime labels are causal but thresholds were fixed in the protocol; low-sample slices are descriptive only.",
        ],
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": overall_status,
                "recommended": recommended,
                "pooled_mae_bps": {
                    name: round(pooled_metrics[name]["close_mae_bps"], 4)
                    for name in (
                        "persistence",
                        "statistical_drift",
                        "patron_absolute",
                        "patron_residual",
                        "deployed_patron",
                    )
                },
                "fold_mae_bps": [
                    {
                        "fold": fold["fold"],
                        **{
                            name: round(
                                fold["metrics"][name]["close_mae_bps"], 4
                            )
                            for name in (
                                "persistence",
                                "patron_absolute",
                                "patron_residual",
                            )
                        },
                    }
                    for fold in folds
                ],
                "assessments": {
                    name: {
                        "eligible": item["eligible"],
                        "failed": item["failed_checks"],
                    }
                    for name, item in assessments.items()
                },
            },
            indent=2,
        )
    )
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
