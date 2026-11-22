"""Train a PATRON candidate with the quantile-head initialisation fix.

The deployed champion's quantile head was randomly initialised with biases of
roughly +/-0.125 in *relative return* units, while its targets are roughly
+/-0.003. After four epochs those random offsets still dominate the forecast.
This script reuses PATRON's own model, trainer, features and labels, but
initialises the forecast head at persistence with a realistic interval before
training. It never publishes a checkpoint: promotion is a separate decision.

Run from the repository root::

    backend/.venv/Scripts/python.exe scripts/train_patron_candidate.py \
        --config PATRON/configs/candidate_v2.yaml --epochs 24
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import torch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PATRON_DIR = PROJECT_ROOT / "PATRON"
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
# PATRON resolves its data/experiment roots from the working directory when the
# installed wheel is used; chdir before importing so checkpoints land in PATRON.
os.chdir(PATRON_DIR)

from patron.config import load_config  # noqa: E402
from patron.datasets.loader import prepare_data  # noqa: E402
from patron.models.patron_net import build_model, count_parameters  # noqa: E402
from patron.paths import ensure_dirs  # noqa: E402
from patron.training.trainer import train  # noqa: E402


def inverse_softplus(value: float) -> float:
    """Return x such that softplus(x) == value (stable for small values)."""
    return math.log(math.expm1(value))


def initialise_forecast_head(
    model: torch.nn.Module,
    interval_half_width: float = 0.002,
    weight_std: float = 0.01,
) -> dict[str, float]:
    """Set the quantile head to persistence with a narrow, finite interval.

    A randomly initialised 54-output linear layer has biases around +/-0.125,
    i.e. +/-12.5% in return space. That is 40x the typical 15m move and explains
    the champion's huge per-step offsets and 12% wide intervals.
    """
    head = model.quantile_head
    horizon = model.horizon
    fields = model.n_range_fields
    quantiles = model.n_quantiles
    if quantiles != 3:
        raise ValueError("this initialiser expects three quantiles")
    with torch.no_grad():
        head.weight.normal_(mean=0.0, std=weight_std)
        head.bias.zero_()
        bias = head.bias.view(horizon, fields, quantiles)
        spread = inverse_softplus(max(interval_half_width, 1e-5))
        bias[:, :, 1].fill_(spread)
        bias[:, :, 2].fill_(spread)
    return {
        "interval_half_width": interval_half_width,
        "spread_raw": spread,
        "weight_std": weight_std,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="PATRON/configs/candidate_v2.yaml")
    parser.add_argument(
        "--dataset", default="PATRON/data/features/BTCUSDT_dataset.parquet"
    )
    parser.add_argument("--scaler", default="PATRON/data/features/scaler.json")
    parser.add_argument("--run-name", default="kbmti_patron_candidate_v2")
    parser.add_argument("--epochs", type=int, default=24)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--train-stride", type=int, default=4)
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--init-interval", type=float, default=0.002)
    parser.add_argument(
        "--no-init-fix",
        action="store_true",
        help="control run: keep PATRON's default random head initialisation",
    )
    args = parser.parse_args()

    ensure_dirs()
    torch.set_num_threads(max(1, args.threads))
    cfg = load_config(PROJECT_ROOT / args.config)
    data = prepare_data(
        cfg,
        PROJECT_ROOT / args.dataset,
        PROJECT_ROOT / args.scaler,
        train_stride=args.train_stride,
    )
    model = build_model(cfg)
    init_info = None
    if not args.no_init_fix:
        init_info = initialise_forecast_head(model, args.init_interval)
    print(
        json.dumps(
            {
                "parameters": count_parameters(model),
                "train_windows": len(data.bundles.train),
                "val_windows": len(data.bundles.val),
                "init": init_info,
                "config": str(args.config),
            },
            indent=2,
        ),
        flush=True,
    )
    history = train(
        model,
        data,
        cfg,
        run_name=args.run_name,
        max_epochs=args.epochs,
        batch_size=args.batch_size,
        num_threads=args.threads,
        seed=args.seed,
    )
    summary = {
        **{k: v for k, v in history.to_dict().items() if k != "history"},
        "init": init_info,
        "best_checkpoint": str(history.run_dir / "best.pt") if history.run_dir else None,
        "train_windows": len(data.bundles.train),
        "val_windows": len(data.bundles.val),
        "test_windows": len(data.bundles.test),
    }
    print(json.dumps(summary, indent=2))
    if history.run_dir:
        (history.run_dir / "candidate_summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
    return 0 if history.best_epoch > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
