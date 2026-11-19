"""PATRON-backed forecast provider.

PATRON's contract is pinned to BTC/USDT 15m. This provider therefore pulls
authoritative Binance BTC/USDT history itself instead of reusing a chart series
that may belong to MetaTrader 5 or a different timeframe. That is deliberate: the
pretrained weights and scaler were fitted to Binance candles, and feeding a
different venue or a truncated-volume series would silently change the inputs.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.core.config import Settings
from app.core.errors import ForecastUnavailableError, ValidationError
from app.forecasting.base import (
    ForecastOutput,
    ForecastProvider,
    ForecastRequest,
    validate_forecast_output,
)
from app.market_data.binance_history import BinanceHistoryClient
from app.market_data.candles import Candle
from app.patron.service import PatronInferenceService

logger = logging.getLogger(__name__)

PATRON_SYMBOL = "BTC/USDT"
PATRON_SYMBOL_BINANCE = "BTCUSDT"
PATRON_INTERVAL = "15m"
PATRON_HORIZON = 6
PATRON_MODEL_ID = "patron-1.0.0"
ACCEPTED_SYMBOLS = {"BTCUSDT", "BTC/USDT", "BTC-USDT"}


class PatronForecastProvider(ForecastProvider):
    provider_id = "patron"
    model_id = PATRON_MODEL_ID
    tokenizer_id = None  # PATRON uses a feature scaler, not a tokenizer

    def __init__(
        self,
        patron: PatronInferenceService,
        history: BinanceHistoryClient,
        settings: Settings,
    ) -> None:
        self.patron = patron
        self.history = history
        self.settings = settings

    # ----------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        status = self.patron.status()
        ready = bool(status["ready"])
        message = status["message"]
        if not status["enabled"]:
            message = "PATRON is disabled by configuration."
        elif not status["checkpoint_exists"]:
            message = status["message"]
        return {
            "stage": 2,
            "provider": self.provider_id,
            "state": str(status["state"]).lower(),
            "ai_available": ready,
            "model_id": PATRON_MODEL_ID,
            "tokenizer_id": None,
            "device": "cpu" if ready else None,
            "context_limit": 96,
            "horizon": PATRON_HORIZON,
            "message": message,
            "progress": None,
            "checkpoint": status["checkpoint_path"],
            "checkpoint_exists": status["checkpoint_exists"],
            "checkpoint_sha256": status["checkpoint_sha256"],
            "trainable_parameters": status["trainable_parameters"],
            "torch_version": status["torch_version"],
            "patron_version": status["patron_version"],
            "loaded_at": status["loaded_at"],
            "load_ms": status["load_ms"],
            "last_inference_at": status["last_inference_at"],
            "last_success_at": status["last_success_at"],
            "last_latency_ms": status["last_latency_ms"],
            "inference_count": status["inference_count"],
            "failure_count": status["failure_count"],
            "last_error": status["last_error"],
            "contract": {
                "symbol": PATRON_SYMBOL,
                "timeframe": PATRON_INTERVAL,
                "input_candles": 96,
                "warmup_bars": 384,
                "horizon_candles": PATRON_HORIZON,
                "horizon_minutes": 90,
            },
        }

    # -------------------------------------------------------------- inference
    def run(self, request: ForecastRequest) -> ForecastOutput:
        symbol = str(request.symbol or "").strip().upper().replace("_", "")
        if symbol not in ACCEPTED_SYMBOLS:
            raise ValidationError(
                "PATRON is trained only on BTC/USDT 15m spot and cannot forecast "
                f"'{request.symbol}'. Select BTCUSDT and the M15 timeframe.",
                {"supported_symbol": PATRON_SYMBOL, "timeframe": PATRON_INTERVAL},
            )
        if request.timeframe.value != "M15":
            raise ValidationError(
                "PATRON's contract is fixed to 15-minute candles; "
                f"'{request.timeframe.value}' is not supported.",
                {"supported_timeframe": PATRON_INTERVAL},
            )
        if not 1 <= int(request.horizon) <= PATRON_HORIZON:
            raise ValidationError(
                f"PATRON produces {PATRON_HORIZON} future candles; horizon must be 1-{PATRON_HORIZON}.",
                {"requested": request.horizon, "supported": list(range(1, PATRON_HORIZON + 1))},
            )

        self.patron.ensure_loaded(blocking=True)
        if not self.patron.ready:
            raise ForecastUnavailableError(
                self.patron.status()["message"] or "PATRON is not ready.",
                {
                    "patron_state": self.patron.state,
                    "checkpoint": str(self.settings.patron_checkpoint),
                },
            )

        wanted = max(480, int(self.settings.patron_history_bars))
        started = time.perf_counter()
        try:
            rows = self.history.recent(PATRON_SYMBOL_BINANCE, PATRON_INTERVAL, limit=wanted)
        except Exception as exc:  # noqa: BLE001 - normalized for the API layer
            raise ForecastUnavailableError(
                "Binance history required for PATRON inference is unavailable.",
                {"error": str(exc)},
            ) from exc
        if len(rows) < 480:
            raise ForecastUnavailableError(
                "Binance returned too little closed 15m history for PATRON.",
                {"received": len(rows), "required": 480},
            )

        payload = self.patron.forecast_from_candles([row.to_row() for row in rows])
        if payload.get("status") != "OK":
            warnings = (payload.get("data_quality") or {}).get("warnings") or []
            raise ForecastUnavailableError(
                "PATRON declined to produce a forecast for this window.",
                {"warnings": warnings, "status": payload.get("status")},
            )

        horizon = int(request.horizon)
        output, derived_warnings = self._to_candles(payload, rows, horizon)
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
        output.latency_ms = elapsed_ms
        output.runtime = "cpu"
        output.input_candle_count = 96
        output.input_last_bar_at = rows[-1].open_time
        output.warnings = list(derived_warnings)
        output.metadata = {
            "patron": payload,
            "reference_close": float(rows[-1].close),
            "reference_close_time": rows[-1].timestamp_close,
            "last_input_open_time": rows[-1].timestamp_open,
            "checkpoint": str(self.settings.patron_checkpoint),
            "checkpoint_sha256": self.patron.status().get("checkpoint_sha256"),
            "history_bars_used": len(rows),
            "warmup_bars": 384,
            "patron_latency_ms": elapsed_ms,
            "derivation": (
                "close = reference_close × (1 + q50 close); open = previous step close "
                "(step 1 uses the reference close); high/low = q50 high/low bounded by "
                "open/close to satisfy candle geometry. Raw quantiles are preserved in "
                "this metadata — no random or historical prices are substituted."
            ),
        }
        # Reuse the shared contract check so timestamps and OHLC invariants are enforced.
        output.warnings.extend(validate_forecast_output(output, request))
        return output

    @staticmethod
    def _to_candles(
        payload: dict[str, Any],
        rows: list[Any],
        horizon: int,
    ) -> tuple[ForecastOutput, list[str]]:
        reference_close = float(rows[-1].close)
        last_open_ms = int(rows[-1].open_time_ms)
        step_ms = 900_000
        warnings: list[str] = []
        adjusted_high = 0
        adjusted_low = 0
        candles: list[Candle] = []
        previous_close = reference_close

        for index, step in enumerate(payload["range_quantiles"][:horizon], start=1):
            close_q = step["close"]
            high_q = step["high"]
            low_q = step["low"]
            close = reference_close * (1.0 + float(close_q["q50"]))
            open_ = previous_close
            high = reference_close * (1.0 + float(high_q["q50"]))
            low = reference_close * (1.0 + float(low_q["q50"]))
            if high < max(open_, close):
                high = max(open_, close)
                adjusted_high += 1
            if low > min(open_, close):
                low = min(open_, close)
                adjusted_low += 1
            candles.append(
                Candle(
                    time=(last_open_ms + step_ms * index) // 1000,
                    open=round(open_, 8),
                    high=round(high, 8),
                    low=round(low, 8),
                    close=round(close, 8),
                    tick_volume=0,
                    real_volume=0,
                    source="patron",
                    symbol="BTCUSDT",
                )
            )
            previous_close = close

        if adjusted_high:
            warnings.append(
                f"{adjusted_high} forecast candle(s) had q50 high below open/close; "
                "high was raised to the enclosing candle boundary for display."
            )
        if adjusted_low:
            warnings.append(
                f"{adjusted_low} forecast candle(s) had q50 low above open/close; "
                "low was lowered to the enclosing candle boundary for display."
            )
        return (
            ForecastOutput(
                candles=candles,
                provider="patron",
                model_id=PATRON_MODEL_ID,
                tokenizer_id=None,
                latency_ms=0.0,
                runtime="cpu",
                input_candle_count=96,
                input_last_bar_at=rows[-1].open_time,
            ),
            warnings,
        )
