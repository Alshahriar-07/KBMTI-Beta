"""Deterministic Trend Pullback strategy.

The evaluator is a pure function of a Phase 1 ``MarketSnapshot`` and a frozen
configuration. It never fetches data, never reads a clock implicitly, and emits no
entry, stop, target, leverage or size. A missing feature produces an explicit
``FEATURE_UNAVAILABLE`` rejection rather than a default bullish/bearish value.

Long rules (mirrored for shorts):

1. Data must be valid, fresh and complete; the market regime must be ``TRENDING_UP``.
2. Structure must be ``UPTREND``, with no adverse CHoCH inside the lookback window.
3. Price must be in a shallow pullback around EMA21, above EMA50, without breaking
   the latest confirmed swing low, and retraced at least the minimum ATR depth.
4. Severe momentum deterioration rejects the setup.
5. Confirmation requires the closed candle to close back above EMA21 with both the
   MACD histogram and RSI improving versus three bars earlier.
6. A confirmed candidate is rejected if the nearest resistance is closer than the
   configured ATR room, or if a confirmed adverse liquidity sweep is nearby.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from app.analysis.contracts import (
    SCOPE_TIMEFRAME_SECONDS,
    MarketSnapshot,
    RegimeState,
    StructureEventType,
    StructureState,
    TrendState,
    ValidationStatus,
)
from app.strategies.config import DEFAULT_CONFIG, STRATEGY_ID, STRATEGY_VERSION, TrendPullbackConfig
from app.strategies.contracts import (
    CheckResult,
    ConfirmationStatus,
    EligibilityAssessment,
    QualityLabel,
    StrategyDecision,
    StrategyDirection,
    StrategyEvidence,
    StrategyQuality,
    StrategyReason,
    TrendPullbackEvaluation,
)

_REQUIRED_FEATURE_FIELDS = (
    "trend.ema9",
    "trend.ema21",
    "trend.ema50",
    "momentum.rsi14",
    "momentum.macd_histogram",
    "momentum.roc_pct",
    "volatility.atr14",
)


def _reason(code: str, message: str, detail: str | None = None) -> StrategyReason:
    return StrategyReason(code=code, message=message, detail=detail)


def _evidence(
    code: str,
    message: str,
    *,
    refs: list[str] | None = None,
    value: float | None = None,
    direction: str | None = None,
) -> StrategyEvidence:
    return StrategyEvidence(code=code, message=message, refs=refs or [], value=value, direction=direction)


def _missing_features(snapshot: MarketSnapshot) -> list[str]:
    missing: list[str] = []
    for field in _REQUIRED_FEATURE_FIELDS:
        section, name = field.split(".", 1)
        value = getattr(getattr(snapshot, section), name, None)
        if value is None:
            missing.append(field)
    if snapshot.trend.state is TrendState.INSUFFICIENT_DATA or not snapshot.trend.meta.valid:
        missing.append("trend")
    if snapshot.structure.state is StructureState.INSUFFICIENT_DATA or not snapshot.structure.meta.valid:
        missing.append("structure")
    if snapshot.volatility.meta.valid is False:
        missing.append("volatility")
    if snapshot.momentum.meta.valid is False:
        missing.append("momentum")
    if snapshot.regime.state is RegimeState.INSUFFICIENT_DATA:
        missing.append("regime")
    return sorted(set(missing))


def _age_bars(snapshot: MarketSnapshot, at: datetime) -> float:
    return (snapshot.data_as_of - at).total_seconds() / SCOPE_TIMEFRAME_SECONDS


def _recent_events(snapshot: MarketSnapshot, event_type: StructureEventType, bars: int) -> list:
    return [
        event
        for event in snapshot.structure.events
        if event.type is event_type and 0 <= _age_bars(snapshot, event.candle_time) <= bars
    ]


def _last_swing(snapshot: MarketSnapshot, kind: str):
    for swing in reversed(snapshot.structure.swings):
        if swing.kind == kind:
            return swing
    return None


def _quality_label(score: int) -> QualityLabel:
    if score >= 75:
        return QualityLabel.HIGH
    if score >= 55:
        return QualityLabel.MEDIUM
    return QualityLabel.LOW


def _quality_score(
    snapshot: MarketSnapshot,
    *,
    direction: StrategyDirection,
    confirmed: bool,
    volatility_penalty: bool,
) -> int:
    score = 50
    if direction is StrategyDirection.LONG:
        score += 15 if snapshot.trend.state is TrendState.STRONG_BULLISH else 10
        score += 5 if any(
            event.type is StructureEventType.BOS_UP for event in _recent_events(snapshot, StructureEventType.BOS_UP, 40)
        ) else 0
        score += 5 if snapshot.momentum.state.value == "BULLISH" else -5 if snapshot.momentum.state.value == "BEARISH" else 0
    else:
        score += 15 if snapshot.trend.state is TrendState.STRONG_BEARISH else 10
        score += 5 if any(
            event.type is StructureEventType.BOS_DOWN
            for event in _recent_events(snapshot, StructureEventType.BOS_DOWN, 40)
        ) else 0
        score += 5 if snapshot.momentum.state.value == "BEARISH" else -5 if snapshot.momentum.state.value == "BULLISH" else 0
    score += 10 if confirmed else 0
    score += 5 if snapshot.volatility.state.value in {"LOW", "NORMAL"} else 0
    score -= 10 if volatility_penalty else 0
    return max(0, min(100, score))


def _finish(
    snapshot: MarketSnapshot,
    *,
    decision: StrategyDecision,
    direction: StrategyDirection,
    confirmation: ConfirmationStatus,
    eligibility: EligibilityAssessment,
    evidence: list[StrategyEvidence],
    rejection_reasons: list[StrategyReason],
    wait_reasons: list[StrategyReason],
    checks: list[CheckResult],
    missing: list[str],
    quality_score: int,
    evaluated_at: datetime,
    config: TrendPullbackConfig,
    warnings: list[str] | None = None,
) -> TrendPullbackEvaluation:
    eligibility = eligibility.model_copy(update={"checks": checks, "missing_features": missing})
    evaluation_id = (
        "evl_"
        + hashlib.sha256(
            f"{snapshot.snapshot_id}|{STRATEGY_ID}|{STRATEGY_VERSION}|{config.config_version}|"
            f"{decision.value}|{direction.value}".encode()
        ).hexdigest()[:24]
    )
    valid_until = snapshot.data_as_of + timedelta(
        seconds=SCOPE_TIMEFRAME_SECONDS * config.valid_bars(decision.value)
    )
    return TrendPullbackEvaluation(
        evaluation_id=evaluation_id,
        strategy_id=STRATEGY_ID,
        strategy_version=STRATEGY_VERSION,
        config_version=config.config_version,
        symbol=snapshot.symbol,
        timeframe=snapshot.timeframe,
        decision=decision,
        direction=direction,
        quality=StrategyQuality(score=quality_score, label=_quality_label(quality_score)),
        eligibility=eligibility,
        confirmation_status=confirmation,
        reference_price=snapshot.last_price,
        evidence=evidence,
        rejection_reasons=rejection_reasons,
        wait_reasons=wait_reasons,
        warnings=list(warnings if warnings is not None else snapshot.warnings),
        market_snapshot_id=snapshot.snapshot_id,
        market_feature_version=snapshot.feature_version,
        data_as_of=snapshot.data_as_of,
        evaluated_at=evaluated_at,
        valid_until=valid_until,
    )


def evaluate_trend_pullback(
    snapshot: MarketSnapshot,
    *,
    config: TrendPullbackConfig = DEFAULT_CONFIG,
    evaluated_at: datetime | None = None,
) -> TrendPullbackEvaluation:
    if evaluated_at is None:
        evaluated_at = snapshot.generated_at
    if evaluated_at.tzinfo is None:
        raise ValueError("evaluated_at must be timezone-aware")
    evaluated_at = evaluated_at.astimezone(UTC)

    checks: list[CheckResult] = []
    evidence: list[StrategyEvidence] = [
        _evidence(
            "MARKET_SNAPSHOT",
            f"Evaluated {snapshot.symbol} {snapshot.timeframe} snapshot {snapshot.snapshot_id}.",
            refs=[snapshot.snapshot_id],
            value=snapshot.last_price,
        )
    ]
    rejection: list[StrategyReason] = []
    waiting: list[StrategyReason] = []
    missing = _missing_features(snapshot)
    pullback_present = False

    trend_aligned = snapshot.trend.state in {
        TrendState.BULLISH,
        TrendState.STRONG_BULLISH,
        TrendState.BEARISH,
        TrendState.STRONG_BEARISH,
    }
    structure_aligned = snapshot.structure.state in {StructureState.UPTREND, StructureState.DOWNTREND}
    regime_compatible = snapshot.regime.state in {RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN}
    eligibility_base = EligibilityAssessment(
        eligible=False,
        trend_aligned=trend_aligned,
        structure_intact=structure_aligned,
        regime_compatible=regime_compatible,
        pullback_present=False,
    )

    checks.append(
        CheckResult(
            name="snapshot_validation",
            passed=snapshot.validation.status is ValidationStatus.OK and not snapshot.is_stale,
            detail=f"validation={snapshot.validation.status.value}, stale={snapshot.is_stale}",
        )
    )
    if snapshot.validation.status is ValidationStatus.INVALID:
        rejection.append(
            _reason(
                "MARKET_DATA_INVALID",
                "The market snapshot failed OHLCV validation.",
                "; ".join(snapshot.validation.errors) or None,
            )
        )
        return _finish(
            snapshot,
            decision=StrategyDecision.NO_TRADE,
            direction=StrategyDirection.NONE,
            confirmation=ConfirmationStatus.NOT_APPLICABLE,
            eligibility=eligibility_base,
            evidence=evidence,
            rejection_reasons=rejection,
            wait_reasons=[],
            checks=checks,
            missing=missing,
            quality_score=0,
            evaluated_at=evaluated_at,
            config=config,
        )
    if snapshot.validation.status is ValidationStatus.INSUFFICIENT_DATA:
        rejection.append(
            _reason(
                "INSUFFICIENT_DATA",
                "The market snapshot does not have enough closed candles for the strategy.",
            )
        )
        return _finish(
            snapshot,
            decision=StrategyDecision.NO_TRADE,
            direction=StrategyDirection.NONE,
            confirmation=ConfirmationStatus.NOT_APPLICABLE,
            eligibility=eligibility_base,
            evidence=evidence,
            rejection_reasons=rejection,
            wait_reasons=[],
            checks=checks,
            missing=missing,
            quality_score=0,
            evaluated_at=evaluated_at,
            config=config,
        )
    if snapshot.is_stale or snapshot.validation.status is ValidationStatus.STALE:
        rejection.append(
            _reason(
                "MARKET_DATA_STALE",
                "The market snapshot is stale; no current setup is evaluated.",
                f"data_as_of={snapshot.data_as_of.isoformat()}",
            )
        )
        return _finish(
            snapshot,
            decision=StrategyDecision.NO_TRADE,
            direction=StrategyDirection.NONE,
            confirmation=ConfirmationStatus.NOT_APPLICABLE,
            eligibility=eligibility_base,
            evidence=evidence,
            rejection_reasons=rejection,
            wait_reasons=[],
            checks=checks,
            missing=missing,
            quality_score=0,
            evaluated_at=evaluated_at,
            config=config,
        )

    checks.append(
        CheckResult(
            name="required_features",
            passed=not missing,
            detail="All required features are available." if not missing else f"Missing: {', '.join(missing)}",
        )
    )
    if missing:
        rejection.append(
            _reason(
                "FEATURE_UNAVAILABLE",
                "Required market-intelligence features are unavailable.",
                ", ".join(missing),
            )
        )
        return _finish(
            snapshot,
            decision=StrategyDecision.NO_TRADE,
            direction=StrategyDirection.NONE,
            confirmation=ConfirmationStatus.NOT_APPLICABLE,
            eligibility=eligibility_base,
            evidence=evidence,
            rejection_reasons=rejection,
            wait_reasons=[],
            checks=checks,
            missing=missing,
            quality_score=0,
            evaluated_at=evaluated_at,
            config=config,
        )

    if snapshot.trend.state in {TrendState.BULLISH, TrendState.STRONG_BULLISH}:
        direction = StrategyDirection.LONG
        expected_regime = RegimeState.TRENDING_UP
        expected_structure = StructureState.UPTREND
    elif snapshot.trend.state in {TrendState.BEARISH, TrendState.STRONG_BEARISH}:
        direction = StrategyDirection.SHORT
        expected_regime = RegimeState.TRENDING_DOWN
        expected_structure = StructureState.DOWNTREND
    else:
        rejection.append(
            _reason(
                "NO_ESTABLISHED_TREND",
                "The EMA trend is neutral, so there is no pullback direction to evaluate.",
                f"trend={snapshot.trend.state.value}",
            )
        )
        return _finish(
            snapshot,
            decision=StrategyDecision.NO_TRADE,
            direction=StrategyDirection.NONE,
            confirmation=ConfirmationStatus.NOT_APPLICABLE,
            eligibility=eligibility_base.model_copy(update={"trend_aligned": False}),
            evidence=evidence,
            rejection_reasons=rejection,
            wait_reasons=[],
            checks=checks,
            missing=missing,
            quality_score=0,
            evaluated_at=evaluated_at,
            config=config,
        )

    evidence.append(
        _evidence(
            "TREND_ALIGNED",
            f"Trend is {snapshot.trend.state.value} ({snapshot.trend.strength.value}).",
            refs=snapshot.trend.evidence,
            value=snapshot.trend.slope_pct_per_bar,
            direction=direction.value,
        )
    )
    evidence.append(
        _evidence(
            "STRUCTURE_STATE",
            f"Structure is {snapshot.structure.state.value}.",
            refs=snapshot.structure.evidence,
            direction=direction.value,
        )
    )
    evidence.append(
        _evidence(
            "REGIME",
            f"Regime is {snapshot.regime.state.value}.",
            refs=snapshot.regime.evidence,
        )
    )

    structure_ok = snapshot.structure.state is expected_structure
    regime_ok = snapshot.regime.state is expected_regime
    checks.append(
        CheckResult(
            name="regime_compatibility",
            passed=regime_ok,
            detail=f"regime={snapshot.regime.state.value}, required={expected_regime.value}",
        )
    )
    checks.append(
        CheckResult(
            name="structure_alignment",
            passed=structure_ok,
            detail=f"structure={snapshot.structure.state.value}, required={expected_structure.value}",
        )
    )

    if not regime_ok:
        rejection.append(
            _reason(
                "REGIME_INCOMPATIBLE",
                "The market regime does not support this pullback direction.",
                f"regime={snapshot.regime.state.value}, required={expected_regime.value}",
            )
        )
        return _finish(
            snapshot,
            decision=StrategyDecision.NO_TRADE,
            direction=StrategyDirection.NONE,
            confirmation=ConfirmationStatus.NOT_APPLICABLE,
            eligibility=eligibility_base.model_copy(update={"regime_compatible": False, "structure_intact": False}),
            evidence=evidence,
            rejection_reasons=rejection,
            wait_reasons=[],
            checks=checks,
            missing=missing,
            quality_score=0,
            evaluated_at=evaluated_at,
            config=config,
        )

    if snapshot.volatility.state.value == "EXTREME":
        rejection.append(
            _reason(
                "VOLATILITY_INCOMPATIBLE",
                "ATR percentile is extreme; a pullback cannot be evaluated reliably.",
                f"atr_percentile={snapshot.volatility.atr_percentile}",
            )
        )
        return _finish(
            snapshot,
            decision=StrategyDecision.NO_TRADE,
            direction=StrategyDirection.NONE,
            confirmation=ConfirmationStatus.NOT_APPLICABLE,
            eligibility=eligibility_base.model_copy(update={"structure_intact": structure_ok}),
            evidence=evidence,
            rejection_reasons=rejection,
            wait_reasons=[],
            checks=checks,
            missing=missing,
            quality_score=0,
            evaluated_at=evaluated_at,
            config=config,
        )

    opposite_structure = snapshot.structure.state is (
        StructureState.DOWNTREND if direction is StrategyDirection.LONG else StructureState.UPTREND
    )
    if opposite_structure:
        rejection.append(
            _reason(
                "STRUCTURE_CONFLICT",
                "Market structure opposes the trend direction.",
                f"structure={snapshot.structure.state.value}",
            )
        )
        return _finish(
            snapshot,
            decision=StrategyDecision.NO_TRADE,
            direction=StrategyDirection.NONE,
            confirmation=ConfirmationStatus.NOT_APPLICABLE,
            eligibility=eligibility_base.model_copy(update={"structure_intact": False}),
            evidence=evidence,
            rejection_reasons=rejection,
            wait_reasons=[],
            checks=checks,
            missing=missing,
            quality_score=0,
            evaluated_at=evaluated_at,
            config=config,
        )

    adverse_choch = StructureEventType.CHOCH_DOWN if direction is StrategyDirection.LONG else StructureEventType.CHOCH_UP
    if _recent_events(snapshot, adverse_choch, config.structure_lookback_bars):
        event = _recent_events(snapshot, adverse_choch, config.structure_lookback_bars)[-1]
        rejection.append(
            _reason(
                "STRUCTURE_INVALIDATED",
                "A recent change of character opposes the trend direction.",
                f"{event.type.value} at {event.candle_time.isoformat()}",
            )
        )
        return _finish(
            snapshot,
            decision=StrategyDecision.NO_TRADE,
            direction=StrategyDirection.NONE,
            confirmation=ConfirmationStatus.NOT_APPLICABLE,
            eligibility=eligibility_base.model_copy(update={"structure_intact": False}),
            evidence=evidence,
            rejection_reasons=rejection,
            wait_reasons=[],
            checks=checks,
            missing=missing,
            quality_score=0,
            evaluated_at=evaluated_at,
            config=config,
        )

    if not structure_ok:
        waiting.append(
            _reason(
                "STRUCTURE_NOT_ALIGNED",
                "Trend is directional but structure has not confirmed it.",
                f"structure={snapshot.structure.state.value}",
            )
        )
        return _finish(
            snapshot,
            decision=StrategyDecision.WAIT,
            direction=StrategyDirection.NONE,
            confirmation=ConfirmationStatus.PENDING,
            eligibility=eligibility_base.model_copy(update={"structure_intact": False}),
            evidence=evidence,
            rejection_reasons=[],
            wait_reasons=waiting,
            checks=checks,
            missing=missing,
            quality_score=0,
            evaluated_at=evaluated_at,
            config=config,
        )

    atr = float(snapshot.volatility.atr14 or 0.0)
    close = float(snapshot.last_price)
    ema21 = float(snapshot.trend.ema21 or 0.0)
    ema50 = float(snapshot.trend.ema50 or 0.0)
    if atr <= 0 or ema21 <= 0 or ema50 <= 0:
        rejection.append(_reason("FEATURE_UNAVAILABLE", "ATR or EMA values are not usable."))
        return _finish(
            snapshot,
            decision=StrategyDecision.NO_TRADE,
            direction=StrategyDirection.NONE,
            confirmation=ConfirmationStatus.NOT_APPLICABLE,
            eligibility=eligibility_base,
            evidence=evidence,
            rejection_reasons=rejection,
            wait_reasons=[],
            checks=checks,
            missing=["volatility.atr14", "trend.ema21", "trend.ema50"],
            quality_score=0,
            evaluated_at=evaluated_at,
            config=config,
        )

    fast_distance = (close - ema21) / atr
    slow_distance = (close - ema50) / atr
    last_high = _last_swing(snapshot, "high")
    last_low = _last_swing(snapshot, "low")
    if direction is StrategyDirection.LONG:
        depth = (last_high.price - close) / atr if last_high else 0.0
        too_deep = slow_distance < -config.max_below_slow_ema_atr or fast_distance < -config.max_below_fast_ema_atr
        broken = bool(last_low and close < last_low.price)
        pullback_present = (
            -config.max_below_fast_ema_atr <= fast_distance <= config.pullback_zone_atr
            and depth >= config.min_pullback_depth_atr
        )
        extended = fast_distance > config.max_extension_atr
    else:
        depth = (close - last_low.price) / atr if last_low else 0.0
        too_deep = slow_distance > config.max_below_slow_ema_atr or fast_distance > config.max_below_fast_ema_atr
        broken = bool(last_high and close > last_high.price)
        pullback_present = (
            -config.max_below_fast_ema_atr <= -fast_distance <= config.pullback_zone_atr
            and depth >= config.min_pullback_depth_atr
        )
        extended = fast_distance < -config.max_extension_atr

    checks.append(
        CheckResult(
            name="pullback_location",
            passed=pullback_present,
            detail=f"close-EMA21={fast_distance:.2f} ATR, close-EMA50={slow_distance:.2f} ATR, depth={depth:.2f} ATR",
            value=fast_distance,
        )
    )
    evidence.append(
        _evidence(
            "PULLBACK_LOCATION",
            f"Price is {fast_distance:+.2f} ATR from EMA21 and {slow_distance:+.2f} ATR from EMA50; "
            f"retracement depth is {depth:.2f} ATR.",
            refs=[snapshot.structure.evidence[-1]] if snapshot.structure.evidence else [],
            value=depth,
            direction=direction.value,
        )
    )

    if too_deep:
        rejection.append(
            _reason(
                "PULLBACK_TOO_DEEP",
                "The pullback has extended beyond the documented trend area.",
                f"close-EMA50={slow_distance:.2f} ATR, close-EMA21={fast_distance:.2f} ATR",
            )
        )
        return _finish(
            snapshot,
            decision=StrategyDecision.NO_TRADE,
            direction=StrategyDirection.NONE,
            confirmation=ConfirmationStatus.NOT_APPLICABLE,
            eligibility=eligibility_base,
            evidence=evidence,
            rejection_reasons=rejection,
            wait_reasons=[],
            checks=checks,
            missing=missing,
            quality_score=0,
            evaluated_at=evaluated_at,
            config=config,
        )
    if broken:
        level = last_low if direction is StrategyDirection.LONG else last_high
        rejection.append(
            _reason(
                "PULLBACK_INVALIDATED",
                "Price closed beyond the latest confirmed swing level, invalidating the pullback.",
                f"swing={level.kind} {level.price}",
            )
        )
        return _finish(
            snapshot,
            decision=StrategyDecision.NO_TRADE,
            direction=StrategyDirection.NONE,
            confirmation=ConfirmationStatus.NOT_APPLICABLE,
            eligibility=eligibility_base.model_copy(update={"structure_intact": False}),
            evidence=evidence,
            rejection_reasons=rejection,
            wait_reasons=[],
            checks=checks,
            missing=missing,
            quality_score=0,
            evaluated_at=evaluated_at,
            config=config,
        )
    if not pullback_present or extended:
        waiting.append(
            _reason(
                "PULLBACK_NOT_PRESENT",
                "Trend is eligible but price is not in a documented pullback zone.",
                f"close-EMA21={fast_distance:.2f} ATR, depth={depth:.2f} ATR"
                if direction is StrategyDirection.LONG
                else f"EMA21-close={-fast_distance:.2f} ATR, depth={depth:.2f} ATR",
            )
        )
        return _finish(
            snapshot,
            decision=StrategyDecision.WAIT,
            direction=StrategyDirection.NONE,
            confirmation=ConfirmationStatus.PENDING,
            eligibility=eligibility_base.model_copy(update={"pullback_present": False}),
            evidence=evidence,
            rejection_reasons=[],
            wait_reasons=waiting,
            checks=checks,
            missing=missing,
            quality_score=0,
            evaluated_at=evaluated_at,
            config=config,
        )

    histogram_change = snapshot.momentum.macd_histogram_change
    rsi_change = snapshot.momentum.rsi_change
    rsi = float(snapshot.momentum.rsi14 or 0.0)
    roc = float(snapshot.momentum.roc_pct or 0.0)
    if histogram_change is None or rsi_change is None:
        rejection.append(_reason("FEATURE_UNAVAILABLE", "Momentum change values are unavailable."))
        return _finish(
            snapshot,
            decision=StrategyDecision.NO_TRADE,
            direction=StrategyDirection.NONE,
            confirmation=ConfirmationStatus.NOT_APPLICABLE,
            eligibility=eligibility_base,
            evidence=evidence,
            rejection_reasons=rejection,
            wait_reasons=[],
            checks=checks,
            missing=["momentum.macd_histogram_change", "momentum.rsi_change"],
            quality_score=0,
            evaluated_at=evaluated_at,
            config=config,
        )

    if direction is StrategyDirection.LONG:
        deteriorated = rsi <= config.severe_rsi_long or (
            snapshot.momentum.state.value == "BEARISH"
            and histogram_change < 0
            and roc < -config.momentum_roc_deterioration_pct
        )
    else:
        deteriorated = rsi >= config.severe_rsi_short or (
            snapshot.momentum.state.value == "BULLISH"
            and histogram_change > 0
            and roc > config.momentum_roc_deterioration_pct
        )
    checks.append(
        CheckResult(
            name="momentum_health",
            passed=not deteriorated,
            detail=f"rsi={rsi:.2f}, histogram_change={histogram_change:.6f}, roc={roc:.3f}%",
            value=rsi,
        )
    )
    if deteriorated:
        rejection.append(
            _reason(
                "MOMENTUM_DETERIORATION",
                "Momentum deterioration exceeds the documented pullback tolerance.",
                f"rsi={rsi:.2f}, roc={roc:.3f}%, momentum={snapshot.momentum.state.value}",
            )
        )
        return _finish(
            snapshot,
            decision=StrategyDecision.NO_TRADE,
            direction=StrategyDirection.NONE,
            confirmation=ConfirmationStatus.FAILED,
            eligibility=eligibility_base.model_copy(update={"pullback_present": True}),
            evidence=evidence,
            rejection_reasons=rejection,
            wait_reasons=[],
            checks=checks,
            missing=missing,
            quality_score=0,
            evaluated_at=evaluated_at,
            config=config,
        )

    if direction is StrategyDirection.LONG:
        confirmed = close > ema21 and histogram_change > 0 and rsi_change > 0
    else:
        confirmed = close < ema21 and histogram_change < 0 and rsi_change < 0
    evidence.append(
        _evidence(
            "MOMENTUM",
            f"RSI {rsi:.2f} (change {rsi_change:+.2f}), MACD histogram change {histogram_change:+.6f}, "
            f"ROC {roc:+.3f}%.",
            refs=snapshot.momentum.evidence,
            value=histogram_change,
            direction=direction.value,
        )
    )
    checks.append(
        CheckResult(
            name="confirmation",
            passed=confirmed,
            detail=(
                (
                    "Closed candle reclaimed EMA21 with improving MACD histogram and RSI."
                    if direction is StrategyDirection.LONG
                    else "Closed candle lost EMA21 with weakening MACD histogram and RSI."
                )
                if confirmed
                else (
                    "Confirmation requires the closed candle to reclaim EMA21 with improving "
                    "MACD histogram and RSI."
                    if direction is StrategyDirection.LONG
                    else "Confirmation requires the closed candle to lose EMA21 with weakening "
                    "MACD histogram and RSI."
                )
            ),
        )
    )
    if not confirmed:
        if direction is StrategyDirection.LONG and close <= ema21:
            waiting.append(
                _reason(
                    "AWAITING_RECLAIM",
                    "Pullback is present but the closed candle has not reclaimed EMA21.",
                    f"close={close}, ema21={ema21}",
                )
            )
        elif direction is StrategyDirection.SHORT and close >= ema21:
            waiting.append(
                _reason(
                    "AWAITING_RECLAIM",
                    "Pullback is present but the closed candle has not lost EMA21.",
                    f"close={close}, ema21={ema21}",
                )
            )
        else:
            waiting.append(
                _reason(
                    "AWAITING_MOMENTUM_CONFIRMATION",
                    "Price location is acceptable but MACD histogram and RSI are not improving together.",
                    f"histogram_change={histogram_change:+.6f}, rsi_change={rsi_change:+.2f}",
                )
            )
        return _finish(
            snapshot,
            decision=StrategyDecision.WAIT,
            direction=StrategyDirection.NONE,
            confirmation=ConfirmationStatus.PENDING,
            eligibility=eligibility_base.model_copy(update={"pullback_present": True}),
            evidence=evidence,
            rejection_reasons=[],
            wait_reasons=waiting,
            checks=checks,
            missing=missing,
            quality_score=0,
            evaluated_at=evaluated_at,
            config=config,
        )

    evidence.append(
        _evidence(
            "CONFIRMATION",
            "Closed candle reclaimed EMA21 (long) / lost EMA21 (short) with improving MACD histogram and RSI.",
            refs=[*snapshot.trend.evidence, *snapshot.momentum.evidence],
            direction=direction.value,
        )
    )

    if direction is StrategyDirection.LONG:
        resistances = [level for level in snapshot.structure.levels if level.price > close]
        if resistances:
            nearest = min(resistances, key=lambda level: level.price)
            room = (nearest.price - close) / atr
            checks.append(
                CheckResult(
                    name="room_to_resistance",
                    passed=room >= config.min_room_atr,
                    detail=f"nearest resistance {nearest.price} is {room:.2f} ATR away",
                    value=room,
                )
            )
            if room < config.min_room_atr:
                rejection.append(
                    _reason(
                        "RESISTANCE_TOO_CLOSE",
                        "Nearest resistance leaves less than the documented room for a long candidate.",
                        f"room={room:.2f} ATR, required={config.min_room_atr:.2f} ATR",
                    )
                )
                return _finish(
                    snapshot,
                    decision=StrategyDecision.NO_TRADE,
                    direction=StrategyDirection.NONE,
                    confirmation=ConfirmationStatus.FAILED,
                    eligibility=eligibility_base.model_copy(update={"pullback_present": True}),
                    evidence=evidence,
                    rejection_reasons=rejection,
                    wait_reasons=[],
                    checks=checks,
                    missing=missing,
                    quality_score=0,
                    evaluated_at=evaluated_at,
                    config=config,
                )
        adverse_kind = "high"
    else:
        supports = [level for level in snapshot.structure.levels if level.price < close]
        if supports:
            nearest = max(supports, key=lambda level: level.price)
            room = (close - nearest.price) / atr
            checks.append(
                CheckResult(
                    name="room_to_support",
                    passed=room >= config.min_room_atr,
                    detail=f"nearest support {nearest.price} is {room:.2f} ATR away",
                    value=room,
                )
            )
            if room < config.min_room_atr:
                rejection.append(
                    _reason(
                        "SUPPORT_TOO_CLOSE",
                        "Nearest support leaves less than the documented room for a short candidate.",
                        f"room={room:.2f} ATR, required={config.min_room_atr:.2f} ATR",
                    )
                )
                return _finish(
                    snapshot,
                    decision=StrategyDecision.NO_TRADE,
                    direction=StrategyDirection.NONE,
                    confirmation=ConfirmationStatus.FAILED,
                    eligibility=eligibility_base.model_copy(update={"pullback_present": True}),
                    evidence=evidence,
                    rejection_reasons=rejection,
                    wait_reasons=[],
                    checks=checks,
                    missing=missing,
                    quality_score=0,
                    evaluated_at=evaluated_at,
                    config=config,
                )
        adverse_kind = "low"

    conflicting = [
        sweep
        for sweep in snapshot.liquidity.sweeps
        if sweep.kind == adverse_kind
        and sweep.confirmation == "CONFIRMED"
        and abs(sweep.level - close) <= config.adverse_sweep_atr * atr
        and 0 <= _age_bars(snapshot, sweep.candle_time) <= config.adverse_sweep_bars
    ]
    checks.append(
        CheckResult(
            name="liquidity_conflict",
            passed=not conflicting,
            detail="No confirmed adverse sweep near price." if not conflicting else f"{len(conflicting)} adverse sweep(s).",
        )
    )
    if conflicting:
        rejection.append(
            _reason(
                "LIQUIDITY_CONFLICT",
                "A confirmed adverse liquidity sweep is close to the candidate price.",
                f"{conflicting[-1].kind} sweep at {conflicting[-1].level}",
            )
        )
        return _finish(
            snapshot,
            decision=StrategyDecision.NO_TRADE,
            direction=StrategyDirection.NONE,
            confirmation=ConfirmationStatus.FAILED,
            eligibility=eligibility_base.model_copy(update={"pullback_present": True}),
            evidence=evidence,
            rejection_reasons=rejection,
            wait_reasons=[],
            checks=checks,
            missing=missing,
            quality_score=0,
            evaluated_at=evaluated_at,
            config=config,
        )

    score = _quality_score(
        snapshot,
        direction=direction,
        confirmed=True,
        volatility_penalty=snapshot.volatility.state.value == "HIGH",
    )
    decision = StrategyDecision.LONG if direction is StrategyDirection.LONG else StrategyDecision.SHORT
    return _finish(
        snapshot,
        decision=decision,
        direction=direction,
        confirmation=ConfirmationStatus.CONFIRMED,
        eligibility=eligibility_base.model_copy(update={"pullback_present": True}),
        evidence=evidence,
        rejection_reasons=[],
        wait_reasons=[],
        checks=checks,
        missing=missing,
        quality_score=score,
        evaluated_at=evaluated_at,
        config=config,
    )
