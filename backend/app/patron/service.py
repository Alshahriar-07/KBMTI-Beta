"""PATRON inference service.

PATRON (Pattern Recognition & Outcome Network) is a CPU PyTorch forecaster, not a
chat model. It consumes a fixed window of 96 closed BTC/USDT 15-minute candles
(plus at least 384 contiguous warm-up bars) and returns four heads:

* candlestick pattern scores,
* triple-barrier probabilities,
* high/low/close quantiles for the next six candles,
* a five-class momentum distribution.

This module owns the one model instance for the process. Loading is lazy,
single-flight and monitored; inference is serialized because the model is small
and CPU-bound. Nothing here fabricates a forecast: if the checkpoint is missing or
the data does not satisfy PATRON's contract, the service reports that state and
``predict`` returns ``NO_OUTPUT`` or raises a typed API error.
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.errors import ApiError, ForecastUnavailableError

logger = logging.getLogger(__name__)

WARMUP_BARS = 384
SEQUENCE_LENGTH = 96
TIMEFRAME_SECONDS = 900
REQUIRED_CANDLES = WARMUP_BARS + SEQUENCE_LENGTH
MODEL_ID = "patron-1.0.0"

STATE_DISABLED = "DISABLED"
STATE_NOT_CONFIGURED = "NOT_CONFIGURED"
STATE_LOADING = "LOADING"
STATE_READY = "READY"
STATE_ERROR = "ERROR"


def _iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _package_version(name: str) -> str | None:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:  # pragma: no cover - metadata may be absent in odd installs
        return None


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


class PatronInferenceService:
    """Single-process, thread-safe owner of the PATRON predictor."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._state = STATE_DISABLED if not settings.patron_enabled else STATE_NOT_CONFIGURED
        self._message = (
            "PATRON is disabled by configuration (KBMTI_PATRON_ENABLED=false)."
            if not settings.patron_enabled
            else "PATRON has not been loaded yet."
        )
        self._predictor: Any | None = None
        self._load_lock = threading.Lock()
        self._infer_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self._loaded_at: str | None = None
        self._load_ms: float | None = None
        self._last_error: str | None = None
        self._last_error_kind: str | None = None
        self._last_inference_at: str | None = None
        self._last_success_at: str | None = None
        self._last_latency_ms: float | None = None
        self._last_status: str | None = None
        self._last_as_of: str | None = None
        self._inference_count = 0
        self._failure_count = 0
        self._torch_version: str | None = None
        self._patron_version: str | None = None
        self._parameter_count: int | None = None
        self._feature_order: list[str] = []
        self._sequence_length = SEQUENCE_LENGTH
        self._horizon = 6
        self._checkpoint_sha256 = _sha256(self.settings.patron_checkpoint)
        if not settings.patron_enabled:
            return
        if not self.settings.patron_checkpoint.is_file():
            self._message = self._missing_checkpoint_message()

    # ------------------------------------------------------------------ paths
    def _missing_checkpoint_message(self) -> str:
        return (
            f"PATRON checkpoint not found at {self.settings.patron_checkpoint}. "
            "Train one with: python scripts/train_patron.py "
            "(downloads Binance BTC/USDT 15m history, builds the PATRON dataset and "
            "trains a checkpoint; see README). No forecast is produced until then."
        )

    @property
    def checkpoint(self) -> Path:
        return self.settings.patron_checkpoint

    @property
    def state(self) -> str:
        with self._state_lock:
            return self._state

    @property
    def ready(self) -> bool:
        return self.state == STATE_READY and self._predictor is not None

    # ------------------------------------------------------------------ load
    def start_background_load(self) -> threading.Thread:
        """Kick off the single allowed load without blocking application startup."""

        def runner() -> None:
            try:
                self.ensure_loaded(blocking=True)
            except Exception:  # pragma: no cover - ensure_loaded records errors
                logger.exception("PATRON background load failed")

        thread = threading.Thread(target=runner, name="kbmti-patron-load", daemon=True)
        thread.start()
        return thread

    def ensure_loaded(self, blocking: bool = True) -> dict[str, Any]:
        """Load the checkpoint at most once. Safe under concurrent callers."""

        if not self.settings.patron_enabled:
            return self.status()
        if self._predictor is not None and self.state == STATE_READY:
            return self.status()
        if not self.settings.patron_checkpoint.is_file():
            with self._state_lock:
                self._state = STATE_NOT_CONFIGURED
                self._message = self._missing_checkpoint_message()
            return self.status()
        if not blocking and self.state == STATE_LOADING:
            return self.status()

        with self._load_lock:
            # Double-checked: a second request that waited must not reload the model.
            if self._predictor is not None and self.state == STATE_READY:
                return self.status()
            self._load()
        return self.status()

    def _load(self) -> None:
        with self._state_lock:
            self._state = STATE_LOADING
            self._message = "Loading the PATRON checkpoint and feature scaler."
        started = time.perf_counter()
        try:
            import torch
            from patron.inference.pipeline import load_predictor
            from patron.models.patron_net import count_parameters

            torch.set_num_threads(max(1, int(self.settings.patron_threads)))
            kwargs: dict[str, Any] = {}
            config_path = self.settings.patron_config_path
            if config_path.is_file():
                # The checkpoint embeds its config; pass the file only when present.
                kwargs["config_path"] = str(config_path)
            if self.settings.patron_warmup_path.is_file():
                kwargs["warmup_path"] = str(self.settings.patron_warmup_path)
            predictor = load_predictor(
                checkpoint_path=self.settings.patron_checkpoint,
                **kwargs,
            )
            cfg = predictor.cfg
            if int(cfg.sequence_length) != SEQUENCE_LENGTH:
                raise ValueError(
                    f"checkpoint expects {cfg.sequence_length} candles; "
                    f"KBMTI implements PATRON's {SEQUENCE_LENGTH}-candle contract"
                )
            if cfg.symbol != "BTC/USDT" or cfg.timeframe != "15m":
                raise ValueError(
                    f"checkpoint contract is {cfg.symbol} {cfg.timeframe}; "
                    "KBMTI only serves PATRON's BTC/USDT 15m contract"
                )
            if list(predictor.metadata.get("feature_order") or []) != list(cfg.feature_order):
                raise ValueError("checkpoint feature_order does not match its embedded config")
            self._predictor = predictor
            self._parameter_count = count_parameters(predictor.model)
            self._feature_order = list(cfg.feature_order)
            self._sequence_length = int(cfg.sequence_length)
            self._horizon = int(cfg.horizon)
            self._torch_version = getattr(torch, "__version__", None)
            try:
                import patron

                self._patron_version = getattr(patron, "__version__", None)
            except Exception:  # pragma: no cover
                self._patron_version = None
            self._loaded_at = _iso_now()
            self._load_ms = round((time.perf_counter() - started) * 1000.0, 1)
            self._checkpoint_sha256 = _sha256(self.settings.patron_checkpoint)
            with self._state_lock:
                self._state = STATE_READY
                self._last_error = None
                self._last_error_kind = None
                self._message = (
                    f"PATRON {cfg.project.version} ready on CPU "
                    f"({self._parameter_count:,} parameters, {self._sequence_length}×"
                    f"{len(self._feature_order)} input)."
                )
            logger.info(
                "PATRON loaded from %s in %.0f ms (%s parameters)",
                self.settings.patron_checkpoint,
                self._load_ms,
                f"{self._parameter_count:,}",
            )
        except Exception as exc:  # noqa: BLE001 - every load failure is reported, not hidden
            with self._state_lock:
                self._state = STATE_ERROR
                self._message = f"PATRON failed to load: {exc}"
                self._last_error = str(exc)
                self._last_error_kind = type(exc).__name__
            logger.exception("PATRON checkpoint load failed")

    def reload(self) -> dict[str, Any]:
        """Drop the current predictor and load again (single-flight)."""

        with self._load_lock:
            with self._infer_lock:
                self._predictor = None
            self._state = STATE_NOT_CONFIGURED
            self._message = "Reload requested."
        return self.ensure_loaded(blocking=True)

    def shutdown(self) -> None:
        with self._load_lock, self._infer_lock:
            self._predictor = None
            self._state = STATE_DISABLED
            self._message = "The backend is shutting down."

    # -------------------------------------------------------------- inference
    def _require_ready(self) -> None:
        if self.ready:
            return
        self.ensure_loaded(blocking=True)
        if self.ready:
            return
        raise ForecastUnavailableError(
            self._message or "PATRON is not ready.",
            {
                "patron_state": self.state,
                "checkpoint": str(self.settings.patron_checkpoint),
                "checkpoint_exists": self.settings.patron_checkpoint.is_file(),
                "last_error": self._last_error,
            },
        )

    def infer_payload(self, payload: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
        """Run PATRON on an already-built input payload (the 96-candle contract)."""

        self._require_ready()
        from patron.inference.pipeline import (
            InputValidationError,
            predict,
            validate_output,
        )

        started = time.perf_counter()
        try:
            with self._infer_lock:
                result = predict(payload, self._predictor, now=now)
                validate_output(result)
        except InputValidationError as exc:
            with self._state_lock:
                self._failure_count += 1
                self._last_error = str(exc)
                self._last_error_kind = "InputValidationError"
            raise ApiError(
                "PATRON_INPUT_INVALID",
                f"PATRON rejected the input: {exc}",
                422,
                {"contract": "96 closed BTC/USDT 15m candles, oldest -> newest"},
            ) from exc
        except ApiError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface inference failure, never fake a result
            with self._state_lock:
                self._failure_count += 1
                self._last_error = str(exc)
                self._last_error_kind = type(exc).__name__
            logger.exception("PATRON inference failed")
            raise ApiError(
                "PATRON_INFERENCE_FAILED",
                "PATRON inference failed. No forecast was produced.",
                500,
                {"error": type(exc).__name__},
            ) from exc
        self._record_result(result, started)
        return result

    def forecast_from_candles(
        self,
        candles: list[dict[str, Any]],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Build PATRON's window + warm-up from Binance candles and run inference.

        ``candles`` must be closed 15-minute bars, oldest -> newest, with float
        ``volume``. At least 480 bars are required (384 warm-up + 96 window).
        """

        self._require_ready()
        if len(candles) < REQUIRED_CANDLES:
            raise ApiError(
                "PATRON_HISTORY_INSUFFICIENT",
                (
                    f"PATRON needs at least {REQUIRED_CANDLES} closed 15m candles "
                    f"(384 warm-up + 96 window); received {len(candles)}."
                ),
                422,
                {"required": REQUIRED_CANDLES, "received": len(candles)},
            )

        ordered = sorted(candles, key=lambda row: int(row["open_time_ms"]))
        window_rows = ordered[-REQUIRED_CANDLES:]
        self._assert_contiguous(window_rows)

        import pandas as pd

        frame = pd.DataFrame(
            {
                "timestamp_open": pd.to_datetime(
                    [row["open_time_ms"] for row in window_rows], unit="ms", utc=True
                ),
                "open": [float(row["open"]) for row in window_rows],
                "high": [float(row["high"]) for row in window_rows],
                "low": [float(row["low"]) for row in window_rows],
                "close": [float(row["close"]) for row in window_rows],
                "volume": [float(row["volume"]) for row in window_rows],
            }
        )
        frame["timestamp_close"] = frame["timestamp_open"] + pd.Timedelta(minutes=15)
        warmup = frame.iloc[:WARMUP_BARS].copy()
        window = frame.iloc[WARMUP_BARS:]
        payload = {
            "symbol": "BTC/USDT",
            "timeframe": "15m",
            "candles": [
                {
                    "timestamp": row.timestamp_open.isoformat(),
                    "open": float(row.open),
                    "high": float(row.high),
                    "low": float(row.low),
                    "close": float(row.close),
                    "volume": float(row.volume),
                }
                for row in window.itertuples(index=False)
            ],
        }
        predictor = replace(self._predictor, warmup_frame=warmup)
        return self.infer_with(predictor, payload, now=now)

    def infer_with(
        self,
        predictor: Any,
        payload: dict[str, Any],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Run inference with a per-request predictor that carries fresh warm-up bars."""

        from patron.inference.pipeline import (
            InputValidationError,
            predict,
            validate_output,
        )

        started = time.perf_counter()
        try:
            with self._infer_lock:
                result = predict(payload, predictor, now=now)
                validate_output(result)
        except InputValidationError as exc:
            with self._state_lock:
                self._failure_count += 1
                self._last_error = str(exc)
                self._last_error_kind = "InputValidationError"
            raise ApiError(
                "PATRON_INPUT_INVALID",
                f"PATRON rejected the input: {exc}",
                422,
                {"contract": "96 closed BTC/USDT 15m candles, oldest -> newest"},
            ) from exc
        except ApiError:
            raise
        except Exception as exc:  # noqa: BLE001
            with self._state_lock:
                self._failure_count += 1
                self._last_error = str(exc)
                self._last_error_kind = type(exc).__name__
            logger.exception("PATRON inference failed")
            raise ApiError(
                "PATRON_INFERENCE_FAILED",
                "PATRON inference failed. No forecast was produced.",
                500,
                {"error": type(exc).__name__},
            ) from exc
        self._record_result(result, started)
        return result

    @staticmethod
    def _assert_contiguous(rows: list[dict[str, Any]]) -> None:
        previous: int | None = None
        for row in rows:
            current = int(row["open_time_ms"])
            if previous is not None and current - previous != TIMEFRAME_SECONDS * 1000:
                raise ApiError(
                    "PATRON_HISTORY_GAP",
                    "Binance history contains a gap inside PATRON's required window.",
                    422,
                    {"gap_before": current, "expected_step_ms": TIMEFRAME_SECONDS * 1000},
                )
            previous = current

    def _record_result(self, result: dict[str, Any], started: float) -> None:
        latency = round((time.perf_counter() - started) * 1000.0, 2)
        with self._state_lock:
            self._inference_count += 1
            self._last_inference_at = _iso_now()
            self._last_latency_ms = latency
            self._last_status = str(result.get("status"))
            self._last_as_of = result.get("as_of")
            if result.get("status") == "OK":
                self._last_success_at = self._last_inference_at
                self._last_error = None
                self._last_error_kind = None
            else:
                warnings = (result.get("data_quality") or {}).get("warnings") or []
                self._last_error = (
                    "; ".join(str(item) for item in warnings)
                    or "PATRON returned NO_OUTPUT without warnings."
                )
                self._last_error_kind = "NO_OUTPUT"

    # --------------------------------------------------------------- payloads
    def status(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "enabled": bool(self.settings.patron_enabled),
                "state": self._state,
                "ready": self.ready,
                "ai_available": self.ready,
                "provider": "patron",
                "model_id": MODEL_ID,
                "model_version": MODEL_ID.replace("patron-", ""),
                "architecture": "cnn_bilstm_self_attention",
                "device": "cpu",
                "torch_version": self._torch_version,
                "patron_version": self._patron_version,
                "checkpoint_path": str(self.settings.patron_checkpoint),
                "checkpoint_exists": self.settings.patron_checkpoint.is_file(),
                "checkpoint_sha256": self._checkpoint_sha256,
                "checkpoint_bytes": self.settings.patron_checkpoint.stat().st_size
                if self.settings.patron_checkpoint.is_file()
                else None,
                "config_path": str(self.settings.patron_config_path),
                "config_exists": self.settings.patron_config_path.is_file(),
                "warmup_path": str(self.settings.patron_warmup_path),
                "warmup_exists": self.settings.patron_warmup_path.is_file(),
                "sequence_length": self._sequence_length,
                "feature_count": len(self._feature_order) or 12,
                "warmup_bars": WARMUP_BARS,
                "horizon_candles": self._horizon,
                "horizon_minutes": self._horizon * 15,
                "trainable_parameters": self._parameter_count,
                "threads": self.settings.patron_threads,
                "loaded_at": self._loaded_at,
                "load_ms": self._load_ms,
                "last_inference_at": self._last_inference_at,
                "last_success_at": self._last_success_at,
                "last_latency_ms": self._last_latency_ms,
                "last_status": self._last_status,
                "last_as_of": self._last_as_of,
                "inference_count": self._inference_count,
                "failure_count": self._failure_count,
                "last_error": self._last_error,
                "last_error_kind": self._last_error_kind,
                "message": self._message,
            }

    def info(self) -> dict[str, Any]:
        status = self.status()
        return {
            "model": "PATRON",
            "full_name": "Pattern Recognition & Outcome Network",
            "model_id": MODEL_ID,
            "source": "PATRON v1.0.0-beta.1 (Apache-2.0)",
            "provider": "patron",
            "task": "Short-horizon probabilistic BTC/USDT 15m forecasting",
            "contract": {
                "symbol": "BTC/USDT",
                "timeframe": "15m",
                "input_candles": SEQUENCE_LENGTH,
                "warmup_bars": WARMUP_BARS,
                "feature_count": 12,
                "feature_order": self._feature_order
                or [
                    "open_rel",
                    "high_rel",
                    "low_rel",
                    "close_rel",
                    "volume_log_rel",
                    "body_to_range",
                    "atr14_pct",
                    "rsi14_scaled",
                    "ema9_gap",
                    "ema21_gap",
                    "volume_spike",
                    "htf_trend",
                ],
                "horizon_candles": self._horizon,
                "horizon_minutes": self._horizon * 15,
            },
            "heads": {
                "pattern_scores": "12 independent sigmoid pattern tags",
                "barrier_probabilities": "tp_first / sl_first / timeout (softmax)",
                "range_quantiles": "6 steps × high/low/close × q10/q50/q90",
                "momentum": "5-class softmax (strong_bullish … strong_bearish)",
            },
            "capabilities": {
                "chat": False,
                "streaming": False,
                "order_execution": False,
                "multi_symbol": False,
                "multi_timeframe": False,
                "supported_horizons": list(range(1, self._horizon + 1)),
            },
            "runtime": status,
            "disclaimer": (
                "PATRON is experimental research software. Outputs are probabilistic "
                "estimates, not financial advice, and carry no accuracy guarantee."
            ),
        }

    def health(self) -> dict[str, Any]:
        status = self.status()
        patron_available = importlib.util.find_spec("patron") is not None
        torch_available = importlib.util.find_spec("torch") is not None
        patron_version = status["patron_version"] or _package_version("patron")
        torch_version = status["torch_version"] or _package_version("torch")
        checks = [
            {
                "id": "patron_package",
                "label": "PATRON package",
                "ok": patron_available,
                "status": "pass" if patron_available else "fail",
                "detail": patron_version or "not importable",
            },
            {
                "id": "torch",
                "label": "PyTorch runtime",
                "ok": torch_available,
                "status": "pass" if torch_available else "fail",
                "detail": torch_version or "not importable",
            },
            {
                "id": "checkpoint",
                "label": "Model checkpoint",
                "ok": status["checkpoint_exists"],
                "status": "pass" if status["checkpoint_exists"] else "fail",
                "detail": status["checkpoint_path"],
            },
            {
                "id": "config",
                "label": "Model configuration",
                "ok": status["config_exists"],
                "status": "pass" if status["config_exists"] else "warn",
                "detail": status["config_path"],
            },
            {
                "id": "loaded",
                "label": "Model loaded",
                "ok": status["ready"],
                "status": "pass" if status["ready"] else ("warn" if status["state"] != STATE_ERROR else "fail"),
                "detail": status["message"],
            },
            {
                "id": "last_inference",
                "label": "Last inference",
                "ok": status["last_error"] is None,
                "status": "pass" if status["last_error"] is None else "warn",
                "detail": status["last_error"] or status["last_inference_at"] or "no inference yet",
            },
        ]
        failures = sum(1 for check in checks if check["status"] == "fail")
        warnings = sum(1 for check in checks if check["status"] == "warn")
        overall = "FAIL" if failures else ("WARN" if warnings else "PASS")
        return {
            "healthy": overall != "FAIL" and status["ready"],
            "status": overall,
            "checks": checks,
            "state": status["state"],
            "ready": status["ready"],
            "message": status["message"],
            "last_success_at": status["last_success_at"],
            "last_error": status["last_error"],
            "checked_at": _iso_now(),
        }

    def readiness(self) -> dict[str, Any]:
        """Trigger the lazy load once and report whether inference can start now."""

        if self.settings.patron_enabled and not self.ready:
            self.ensure_loaded(blocking=True)
        status = self.status()
        return {
            "ready": status["ready"],
            "state": status["state"],
            "ai_available": status["ai_available"],
            "model_id": status["model_id"],
            "checkpoint_exists": status["checkpoint_exists"],
            "loaded_at": status["loaded_at"],
            "load_ms": status["load_ms"],
            "message": status["message"],
            "last_error": status["last_error"],
            "checked_at": _iso_now(),
        }
