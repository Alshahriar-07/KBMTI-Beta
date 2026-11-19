from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.core.errors import ValidationError
from app.core.timeframes import Timeframe
from app.forecasting.base import (
    ForecastOutput,
    ForecastRequest,
    validate_forecast_output,
    validate_forecast_request,
)
from app.forecasting.patron_provider import PatronForecastProvider
from app.market_data.candles import Candle

PATRON_CONFIG = Path(__file__).resolve().parents[2] / "PATRON" / "configs" / "model_config.yaml"


def candles(count: int = 10, start: int = 1_700_000_000, step: int = 900) -> list[Candle]:
    return [
        Candle(time=start + index * step, open=100 + index, high=102 + index, low=99 + index, close=101 + index)
        for index in range(count)
    ]


def request(horizon: int = 5, symbol: str = "BTCUSDT", timeframe: Timeframe = Timeframe.M15) -> ForecastRequest:
    return ForecastRequest(symbol=symbol, timeframe=timeframe, candles=candles(), horizon=horizon)


def output(req: ForecastRequest, count: int = 5) -> ForecastOutput:
    step = 900
    start = req.candles[-1].time
    return ForecastOutput(
        candles=[
            Candle(time=start + step * (index + 1), open=110, high=112, low=109, close=111)
            for index in range(count)
        ],
        provider="test",
        model_id="patron-1.0.0",
        tokenizer_id=None,
        latency_ms=12.0,
        runtime="cpu",
        input_candle_count=len(req.candles),
        input_last_bar_at=start,
    )


def test_valid_request_passes() -> None:
    validate_forecast_request(request())


def test_unsorted_or_duplicate_requests_are_rejected() -> None:
    req = request()
    req.candles = list(reversed(req.candles))
    with pytest.raises(ValueError):
        validate_forecast_request(req)

    req = request()
    req.candles = [req.candles[0]] * 3
    with pytest.raises(ValueError):
        validate_forecast_request(req)


def test_horizon_bounds() -> None:
    with pytest.raises(ValueError):
        validate_forecast_request(request(horizon=0))
    with pytest.raises(ValueError):
        validate_forecast_request(request(horizon=30))


def test_valid_output_passes() -> None:
    req = request()
    assert validate_forecast_output(output(req), req) == []


def test_output_count_must_match_horizon() -> None:
    req = request()
    with pytest.raises(ValueError):
        validate_forecast_output(output(req, count=3), req)


def test_output_ohlc_invariants_are_enforced() -> None:
    req = request()
    bad = output(req)
    bad.candles[0] = Candle(time=req.candles[-1].time + 900, open=110, high=105, low=109, close=111)
    with pytest.raises(ValueError):
        validate_forecast_output(bad, req)


def test_output_timestamps_must_continue_after_input() -> None:
    req = request()
    bad = output(req)
    bad.candles[0] = Candle(time=req.candles[-1].time, open=110, high=112, low=109, close=111)
    with pytest.raises(ValueError):
        validate_forecast_output(bad, req)


@pytest.fixture
def provider() -> PatronForecastProvider:
    settings = Settings(patron_autoload=False, patron_checkpoint=Path("missing.pt"))
    return PatronForecastProvider(patron=object(), history=object(), settings=settings)  # type: ignore[arg-type]


def test_patron_rejects_non_btc_symbol_before_loading(provider: PatronForecastProvider) -> None:
    with pytest.raises(ValidationError) as excinfo:
        provider.run(request(symbol="ETHUSDT"))
    assert "BTC/USDT" in excinfo.value.message


def test_patron_rejects_non_15m_timeframe(provider: PatronForecastProvider) -> None:
    with pytest.raises(ValidationError) as excinfo:
        provider.run(request(timeframe=Timeframe.H1))
    assert "15-minute" in excinfo.value.message


def test_patron_rejects_unsupported_horizon(provider: PatronForecastProvider) -> None:
    with pytest.raises(ValidationError) as excinfo:
        provider.run(request(horizon=9))
    assert "horizon must be 1-6" in excinfo.value.message


def test_patron_candle_derivation_uses_quantiles_not_history() -> None:
    rows = [
        SimpleNamespace(
            open_time_ms=1_700_000_000_000,
            open_time=1_700_000_000,
            close=100.0,
            timestamp_close="2023-11-14T22:15:00+00:00",
            timestamp_open="2023-11-14T22:00:00+00:00",
        )
    ]
    payload = {
        "range_quantiles": [
            {
                "step": 1,
                "minutes_ahead": 15,
                "high": {"q10": 0.0, "q50": 0.01, "q90": 0.02},
                "low": {"q10": -0.02, "q50": -0.01, "q90": 0.0},
                "close": {"q10": -0.01, "q50": 0.005, "q90": 0.02},
            }
        ]
    }
    output, warnings = PatronForecastProvider._to_candles(payload, rows, 1)
    candle = output.candles[0]
    assert candle.time == 1_700_000_900
    assert candle.open == 100.0
    assert candle.close == pytest.approx(100.5)
    assert candle.high == pytest.approx(101.0)
    assert candle.low == pytest.approx(99.0)
    assert candle.source == "patron"
    assert warnings == []
