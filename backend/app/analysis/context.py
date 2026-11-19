"""Build one immutable, reproducible BTCUSDT M15 market snapshot.

Temporal integrity rules enforced here:

* a candle is eligible only when ``open_time + timeframe_seconds <= now``;
* the snapshot's ``as_of`` is the close time of the newest eligible candle, so
  every eligible candle satisfies ``open_time + timeframe_seconds <= as_of``;
* a forming candle (close time in the future) is dropped, never analysed;
* a feature never receives a candle newer than the snapshot's ``as_of``;
* invalid OHLCV stops feature calculation instead of being repaired silently.

The builder is pure with respect to the clock (injected) and the input list; the
service layer owns fetching, caching and persistence.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from app.analysis.contracts import (
    FEATURE_VERSION,
    MAX_ANALYSIS_BARS,
    MIN_ANALYSIS_BARS,
    SCOPE_TIMEFRAME_SECONDS,
    DataProvenance,
    MarketSnapshot,
    SnapshotScope,
    ValidationState,
    ValidationStatus,
    scope_for,
)
from app.analysis.liquidity import evaluate_liquidity, unavailable_liquidity
from app.analysis.momentum import evaluate_momentum, insufficient_momentum
from app.analysis.regime import classify_regime
from app.analysis.structure import evaluate_structure, insufficient_structure
from app.analysis.trend import evaluate_trend, insufficient_trend
from app.analysis.util import series_value, utc_from_epoch
from app.analysis.volatility import evaluate_volatility, insufficient_volatility
from app.core.errors import MarketDataUnavailableError, UnsupportedScopeError
from app.indicators.engine import compute_indicators
from app.market_data.candles import Candle

class MarketContextBuilder:
    def __init__(
        self,
        *,
        stale_after_seconds: float,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._stale_after_seconds = float(stale_after_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))

    def build(
        self,
        *,
        symbol: str,
        timeframe: str,
        candles: Sequence[Candle],
        provider: str,
        source: str,
        fetched_at: datetime,
        request_id: str | None = None,
        fetch_notes: Sequence[str] = (),
    ) -> MarketSnapshot:
        scope = scope_for(symbol, timeframe)
        if not scope.supported:
            raise UnsupportedScopeError(scope.reason or "Unsupported market scope.", scope.model_dump())

        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("the analysis clock must return a timezone-aware datetime")
        now = now.astimezone(UTC)
        request_id = request_id or uuid.uuid4().hex
        timeframe_seconds = SCOPE_TIMEFRAME_SECONDS

        ordered = sorted(candles, key=lambda candle: int(candle.time))
        now_epoch = int(now.timestamp())
        eligible = [
            candle
            for candle in ordered
            if int(candle.time) + timeframe_seconds <= now_epoch
        ]
        dropped = len(ordered) - len(eligible)
        warnings: list[str] = list(fetch_notes)
        if dropped:
            warnings.append(
                f"{dropped} forming or future candle(s) were excluded; only closed candles are analysed."
            )
        if not eligible:
            raise MarketDataUnavailableError(
                "No closed BTCUSDT M15 candles are available for analysis.",
                {"symbol": scope.symbol, "timeframe": scope.timeframe, "received": len(ordered)},
            )

        eligible = eligible[-MAX_ANALYSIS_BARS:]
        as_of_epoch = int(eligible[-1].time) + timeframe_seconds
        as_of = utc_from_epoch(as_of_epoch)

        errors: list[str] = []
        checks: list[str] = ["closed_candles_only"]
        timestamps = [int(candle.time) for candle in eligible]
        if len(set(timestamps)) != len(timestamps):
            errors.append("Duplicate candle timestamps detected.")
        else:
            checks.append("no_duplicate_timestamps")
        if timestamps != sorted(timestamps):
            errors.append("Candle timestamps are not strictly increasing.")
        else:
            checks.append("monotonic_timestamps")

        for candle in eligible:
            values = (candle.open, candle.high, candle.low, candle.close)
            if not all(math.isfinite(float(value)) and float(value) > 0 for value in values):
                errors.append(f"Candle {int(candle.time)} has a non-finite or non-positive OHLC value.")
                break
            if candle.high < max(candle.open, candle.close) or candle.low > min(candle.open, candle.close):
                errors.append(f"Candle {int(candle.time)} violates OHLC geometry (high/low vs open/close).")
                break
            if candle.high < candle.low:
                errors.append(f"Candle {int(candle.time)} has high below low.")
                break
        if not errors:
            checks.append("ohlcv_integrity")

        warmup_complete = len(eligible) >= MIN_ANALYSIS_BARS
        if warmup_complete:
            checks.append("minimum_warmup")
        else:
            warnings.append(
                f"Only {len(eligible)} closed candles are available; {MIN_ANALYSIS_BARS} are required "
                "for a full analysis."
            )

        age_seconds = (now - as_of).total_seconds()
        stale_limit = timeframe_seconds + self._stale_after_seconds
        is_stale = age_seconds > stale_limit
        if is_stale:
            warnings.append(
                f"Market data is stale: the newest closed candle closed {age_seconds:.0f}s ago "
                f"(limit {stale_limit:.0f}s)."
            )

        if errors:
            validation = ValidationState(status=ValidationStatus.INVALID, checks=checks, errors=errors)
        elif not warmup_complete:
            validation = ValidationState(
                status=ValidationStatus.INSUFFICIENT_DATA,
                checks=checks,
                errors=[],
            )
        elif is_stale:
            validation = ValidationState(status=ValidationStatus.STALE, checks=checks, errors=[])
        else:
            validation = ValidationState(status=ValidationStatus.OK, checks=checks, errors=[])

        calculated_at = now
        feature_source = f"{provider}:{scope.symbol}:{scope.timeframe}:closed"
        last_price = self._last_price(eligible)

        bundle = None
        if not errors and warmup_complete:
            try:
                bundle = compute_indicators(eligible)
            except Exception as exc:  # noqa: BLE001 - an indicator defect must not crash the endpoint
                warnings.append(f"Indicator calculation failed: {exc}")
                validation = ValidationState(
                    status=ValidationStatus.INVALID,
                    checks=checks,
                    errors=[f"Indicator calculation failed: {exc}"],
                )

        if errors or bundle is None:
            trend = insufficient_trend(calculated_at, feature_source, "Analysis unavailable for this series.")
            structure = insufficient_structure(calculated_at, feature_source, "Analysis unavailable for this series.")
            momentum = insufficient_momentum(calculated_at, feature_source, "Analysis unavailable for this series.")
            volatility = insufficient_volatility(
                calculated_at, feature_source, "Analysis unavailable for this series."
            )
            liquidity = unavailable_liquidity(calculated_at, feature_source, "Analysis unavailable for this series.")
            regime = classify_regime(
                trend_state=trend.state,
                structure_state=structure.state,
                volatility_state=volatility.state,
                is_stale=is_stale,
                insufficient=True,
                calculated_at=calculated_at,
                source=feature_source,
            )
        else:
            atr14 = series_value(bundle.atr14)
            trend = evaluate_trend(eligible, bundle, calculated_at=calculated_at, source=feature_source)
            structure = evaluate_structure(
                eligible,
                atr14=atr14,
                calculated_at=calculated_at,
                source=feature_source,
            )
            momentum = evaluate_momentum(eligible, bundle, calculated_at=calculated_at, source=feature_source)
            volatility = evaluate_volatility(eligible, bundle, calculated_at=calculated_at, source=feature_source)
            liquidity = evaluate_liquidity(
                eligible,
                atr14=atr14,
                calculated_at=calculated_at,
                source=feature_source,
            )
            insufficient = any(
                state.value == "INSUFFICIENT_DATA"
                for state in (trend.state, structure.state, momentum.state, volatility.state)
            ) or validation.status is ValidationStatus.INSUFFICIENT_DATA
            regime = classify_regime(
                trend_state=trend.state,
                structure_state=structure.state,
                volatility_state=volatility.state,
                is_stale=is_stale,
                insufficient=insufficient,
                calculated_at=calculated_at,
                source=feature_source,
                evidence=[
                    f"trend:{trend.state.value}",
                    f"structure:{structure.state.value}",
                    f"volatility:{volatility.state.value}",
                ],
            )

        input_hash = _input_hash(scope, provider, eligible)
        snapshot_id = _snapshot_id(input_hash, as_of)
        provenance = DataProvenance(
            provider=provider,
            source=source,
            candle_count=len(eligible),
            first_candle_time=utc_from_epoch(eligible[0].time),
            last_closed_candle_time=as_of,
            fetched_at=fetched_at.astimezone(UTC),
            input_hash=input_hash,
            timeframe_seconds=timeframe_seconds,
        )

        return MarketSnapshot(
            request_id=request_id,
            snapshot_id=snapshot_id,
            symbol=scope.symbol,
            timeframe=scope.timeframe,
            provider=provider,
            generated_at=calculated_at,
            data_as_of=as_of,
            is_stale=is_stale,
            feature_version=FEATURE_VERSION,
            scope=scope,
            provenance=provenance,
            validation=validation,
            warnings=warnings,
            last_price=last_price,
            trend=trend,
            structure=structure,
            momentum=momentum,
            volatility=volatility,
            liquidity=liquidity,
            regime=regime,
        )

    @staticmethod
    def _last_price(candles: Sequence[Candle]) -> float:
        for candle in reversed(candles):
            if math.isfinite(float(candle.close)) and float(candle.close) > 0:
                return float(candle.close)
        raise ValueError("no usable close price in the eligible candles")


def _input_hash(scope: SnapshotScope, provider: str, candles: Sequence[Candle]) -> str:
    digest = hashlib.sha256()
    digest.update(f"{scope.symbol}|{scope.timeframe}|{provider}|{SCOPE_TIMEFRAME_SECONDS}".encode())
    for candle in candles:
        digest.update(
            (
                f"|{int(candle.time)}:{float(candle.open):.8f}:{float(candle.high):.8f}:"
                f"{float(candle.low):.8f}:{float(candle.close):.8f}"
            ).encode()
        )
    return digest.hexdigest()


def _snapshot_id(input_hash: str, as_of: datetime) -> str:
    digest = hashlib.sha256(f"{input_hash}|{FEATURE_VERSION}|{as_of.isoformat()}".encode()).hexdigest()
    return f"mkt_{digest[:28]}"
