"""Transparent, rule-based technical bias engine.

This engine is intentionally NOT described as AI. It produces an inspectable
technical bias from live indicator values, with explicit evidence, conflicting
evidence and invalidation conditions. It defaults to WAIT / NO CLEAR SETUP when
data is stale, incomplete or contradictory.

No order placement exists anywhere in KBMTI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.indicators.engine import IndicatorBundle

ENGINE_ID = "rule-based-technical-v1"
DISCLAIMER = (
    "Rule-based technical analysis for monitoring only. It is not AI, not financial advice, "
    "and not an order or trade instruction."
)
AI_NOTE = (
    "This bias is a deterministic technical rule set and does not use PATRON output. "
    "PATRON probabilistic forecasts are reported separately on the Forecasts page."
)

BUY_BIAS = "BUY BIAS"
SELL_BIAS = "SELL BIAS"
WAIT = "WAIT"
NO_CLEAR_SETUP = "NO CLEAR SETUP"

DIRECTION_BY_LABEL = {
    BUY_BIAS: "bullish",
    SELL_BIAS: "bearish",
    WAIT: "neutral",
    NO_CLEAR_SETUP: "undetermined",
}


@dataclass
class Factor:
    id: str
    label: str
    detail: str
    weight: float
    direction: str  # bullish | bearish | neutral

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "detail": self.detail,
            "weight": round(self.weight, 3),
            "direction": self.direction,
        }


@dataclass
class SignalResult:
    symbol: str
    timeframe: str
    label: str
    direction: str
    score: float
    generated_at: str
    data_as_of: str | None
    freshness: str
    supporting: list[Factor] = field(default_factory=list)
    conflicting: list[Factor] = field(default_factory=list)
    neutral: list[Factor] = field(default_factory=list)
    invalidation: list[str] = field(default_factory=list)
    metrics: dict[str, float | None] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    source_candle_count: int = 0
    engine: str = ENGINE_ID
    ai_available: bool = False
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "label": self.label,
            "direction": self.direction,
            "score": round(self.score, 3),
            "generated_at": self.generated_at,
            "data_as_of": self.data_as_of,
            "freshness": self.freshness,
            "supporting": [factor.to_dict() for factor in self.supporting],
            "conflicting": [factor.to_dict() for factor in self.conflicting],
            "neutral": [factor.to_dict() for factor in self.neutral],
            "invalidation": self.invalidation,
            "metrics": self.metrics,
            "warnings": self.warnings,
            "source_candle_count": self.source_candle_count,
            "engine": self.engine,
            "ai_available": self.ai_available,
            "ai_note": AI_NOTE,
            "disclaimer": self.disclaimer,
        }


def _fmt(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "unavailable"
    return f"{value:,.{digits}f}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def evaluate_signal(
    symbol: str,
    timeframe: str,
    bundle: IndicatorBundle,
    *,
    close: float | None,
    completed_candle_count: int,
    data_as_of: str | None,
    freshness: str,
    stale_reason: str | None = None,
    spread_points: int | None = None,
    atr_value: float | None = None,
) -> SignalResult:
    """Build a fully explainable technical bias."""

    latest = bundle.latest()
    price = close if close is not None else latest.get("ema9")
    supporting: list[Factor] = []
    conflicting: list[Factor] = []
    neutral: list[Factor] = []
    invalidation: list[str] = []

    required_bars = bundle.warmup_bars()
    base = SignalResult(
        symbol=symbol,
        timeframe=timeframe,
        label=NO_CLEAR_SETUP,
        direction=DIRECTION_BY_LABEL[NO_CLEAR_SETUP],
        score=0.0,
        generated_at=_now_iso(),
        data_as_of=data_as_of,
        freshness=freshness,
        metrics={**latest, "close": price},
        source_candle_count=completed_candle_count,
    )

    if completed_candle_count < required_bars:
        base.warnings.append(
            f"Only {completed_candle_count} completed candles are available; {required_bars} are required "
            f"for full indicator warm-up."
        )
        base.invalidation.append(
            f"Load at least {required_bars} completed {timeframe} candles before reading a technical bias."
        )
        return base

    if freshness != "fresh":
        base.label = WAIT
        base.direction = DIRECTION_BY_LABEL[WAIT]
        base.warnings.append(
            f"Market data is stale: {stale_reason}"
            if stale_reason
            else "Market data is not fresh; a bias cannot be confirmed."
        )
        base.invalidation.append("Refresh the MT5 feed; the current data is stale.")
        return base

    factor_weights: list[Factor] = []

    # --- Trend structure via EMA alignment -----------------------------------
    ema9, ema21, ema50 = latest.get("ema9"), latest.get("ema21"), latest.get("ema50")
    if price is not None and ema21 is not None and ema50 is not None:
        if ema9 is not None and ema9 > ema21 > ema50 and price > ema9:
            factor = Factor(
                "trend_stack",
                "Bullish EMA structure",
                f"EMA 9 ({_fmt(ema9)}) > EMA 21 ({_fmt(ema21)}) > EMA 50 ({_fmt(ema50)}) with price above EMA 9.",
                0.32,
                "bullish",
            )
        elif ema9 is not None and ema9 < ema21 < ema50 and price < ema9:
            factor = Factor(
                "trend_stack",
                "Bearish EMA structure",
                f"EMA 9 ({_fmt(ema9)}) < EMA 21 ({_fmt(ema21)}) < EMA 50 ({_fmt(ema50)}) with price below EMA 9.",
                0.32,
                "bearish",
            )
        elif price > ema50 and ema21 > ema50:
            factor = Factor(
                "trend_stack",
                "Mildly bullish EMA structure",
                f"Price is above EMA 50 ({_fmt(ema50)}) and EMA 21 is above EMA 50, but EMA 9 is not cleanly stacked.",
                0.16,
                "bullish",
            )
        elif price < ema50 and ema21 < ema50:
            factor = Factor(
                "trend_stack",
                "Mildly bearish EMA structure",
                f"Price is below EMA 50 ({_fmt(ema50)}) and EMA 21 is below EMA 50, but EMA 9 is not cleanly stacked.",
                0.16,
                "bearish",
            )
        else:
            factor = Factor(
                "trend_stack",
                "Mixed EMA structure",
                f"EMA 9/21/50 ({_fmt(ema9)}, {_fmt(ema21)}, {_fmt(ema50)}) are not aligned, so trend direction is unclear.",
                0.0,
                "neutral",
            )
        factor_weights.append(factor)

    # --- RSI momentum ---------------------------------------------------------
    rsi_value = latest.get("rsi14")
    if rsi_value is not None:
        if 55 <= rsi_value <= 70:
            factor = Factor("rsi", "RSI supports upside momentum", f"RSI 14 is {_fmt(rsi_value, 1)}, in the bullish momentum band.", 0.2, "bullish")
        elif 30 <= rsi_value <= 45:
            factor = Factor("rsi", "RSI supports downside momentum", f"RSI 14 is {_fmt(rsi_value, 1)}, in the bearish momentum band.", 0.2, "bearish")
        elif rsi_value > 70:
            factor = Factor(
                "rsi",
                "RSI overbought (caution)",
                f"RSI 14 is {_fmt(rsi_value, 1)}; momentum is extended, which is treated as caution rather than a reversal call.",
                0.0,
                "neutral",
            )
        elif rsi_value < 30:
            factor = Factor(
                "rsi",
                "RSI oversold (caution)",
                f"RSI 14 is {_fmt(rsi_value, 1)}; downside momentum is extended, which is treated as caution rather than a reversal call.",
                0.0,
                "neutral",
            )
        else:
            factor = Factor("rsi", "RSI neutral", f"RSI 14 is {_fmt(rsi_value, 1)}, showing no directional momentum edge.", 0.0, "neutral")
        factor_weights.append(factor)

    # --- MACD momentum --------------------------------------------------------
    hist = latest.get("macd_histogram")
    macd_line = latest.get("macd")
    macd_signal = latest.get("macd_signal")
    if hist is not None and macd_line is not None and macd_signal is not None:
        if hist > 0 and macd_line > 0:
            factor = Factor("macd", "MACD bullish", f"MACD histogram is positive ({hist:,.4f}) with the MACD line above zero.", 0.18, "bullish")
        elif hist < 0 and macd_line < 0:
            factor = Factor("macd", "MACD bearish", f"MACD histogram is negative ({hist:,.4f}) with the MACD line below zero.", 0.18, "bearish")
        elif hist > 0:
            factor = Factor("macd", "MACD improving", f"MACD histogram is positive ({hist:,.4f}) but below the zero line.", 0.09, "bullish")
        elif hist < 0:
            factor = Factor("macd", "MACD deteriorating", f"MACD histogram is negative ({hist:,.4f}) but above the zero line.", 0.09, "bearish")
        else:
            factor = Factor("macd", "MACD flat", "MACD histogram is flat around zero.", 0.0, "neutral")
        factor_weights.append(factor)

    # --- Bollinger position ---------------------------------------------------
    upper, lower, middle = latest.get("bb_upper"), latest.get("bb_lower"), latest.get("bb_middle")
    if price is not None and upper is not None and lower is not None and upper > lower:
        position = (price - lower) / (upper - lower)
        base.metrics["bb_position"] = round(position, 3)
        if position >= 1.0:
            factor = Factor(
                "bollinger",
                "Price above upper band (caution)",
                f"Close is above the upper Bollinger band ({_fmt(upper)}); volatility is extended, which is treated as caution.",
                0.0,
                "neutral",
            )
        elif position <= 0.0:
            factor = Factor(
                "bollinger",
                "Price below lower band (caution)",
                f"Close is below the lower Bollinger band ({_fmt(lower)}); volatility is extended, which is treated as caution.",
                0.0,
                "neutral",
            )
        elif position >= 0.7:
            factor = Factor("bollinger", "Upper half of bands", f"Close sits in the upper half of the Bollinger range around mid-band {_fmt(middle)}.", 0.06, "bullish")
        elif position <= 0.3:
            factor = Factor("bollinger", "Lower half of bands", f"Close sits in the lower half of the Bollinger range around mid-band {_fmt(middle)}.", 0.06, "bearish")
        else:
            factor = Factor("bollinger", "Mid-band balance", f"Close is near the Bollinger mid-band ({_fmt(middle)}).", 0.0, "neutral")
        factor_weights.append(factor)

    score = sum(f.weight if f.direction == "bullish" else -f.weight if f.direction == "bearish" else 0.0 for f in factor_weights)

    for factor in factor_weights:
        if factor.direction == "neutral" or factor.weight == 0:
            neutral.append(factor)
        elif (score >= 0 and factor.direction == "bullish") or (score < 0 and factor.direction == "bearish"):
            supporting.append(factor)
        else:
            conflicting.append(factor)

    base.metrics["score"] = round(score, 3)
    base.supporting = supporting
    base.conflicting = conflicting
    base.neutral = neutral
    base.score = score

    atr_metric = atr_value if atr_value is not None else latest.get("atr14")
    base.metrics["atr14"] = atr_metric

    # --- Decision -------------------------------------------------------------
    if score >= 0.45:
        base.label = BUY_BIAS
        base.direction = DIRECTION_BY_LABEL[BUY_BIAS]
    elif score <= -0.45:
        base.label = SELL_BIAS
        base.direction = DIRECTION_BY_LABEL[SELL_BIAS]
    elif abs(score) < 0.2:
        base.label = NO_CLEAR_SETUP
        base.direction = DIRECTION_BY_LABEL[NO_CLEAR_SETUP]
        base.warnings.append("Indicator evidence is balanced; no directional edge is present.")
    else:
        base.label = WAIT
        base.direction = DIRECTION_BY_LABEL[WAIT]
        base.warnings.append("Signals conflict and the net score is below the bias threshold.")

    if len(conflicting) >= 2:
        if base.label in (BUY_BIAS, SELL_BIAS):
            base.warnings.append("Two or more indicators disagree with the dominant bias; conviction is reduced.")
        if abs(score) < 0.6:
            base.label = WAIT
            base.direction = DIRECTION_BY_LABEL[WAIT]

    if price is not None and ema21 is not None:
        if base.label == BUY_BIAS:
            invalidation.append(f"A completed {timeframe} close below EMA 21 ({_fmt(ema21)}) weakens the bullish view.")
        elif base.label == SELL_BIAS:
            invalidation.append(f"A completed {timeframe} close above EMA 21 ({_fmt(ema21)}) weakens the bearish view.")
        else:
            invalidation.append(
                f"A decisive {timeframe} close outside the EMA 9/21 cluster ({_fmt(ema9)} / {_fmt(ema21)}) is needed to establish direction."
            )

    if atr_metric and price:
        stop_distance = atr_metric * 1.5
        low_side = price - stop_distance
        high_side = price + stop_distance
        invalidation.append(
            f"A {timeframe} move beyond 1.5x ATR 14 ({_fmt(atr_metric)}) from the current close would invalidate "
            f"this read; that is roughly {_fmt(low_side)}–{_fmt(high_side)}."
        )
        base.metrics["atr_stop_distance"] = round(stop_distance, 4)

    if spread_points is not None and atr_metric:
        base.metrics["spread_points"] = spread_points

    base.invalidation.extend(
        [
            "Any new completed candle can change the indicator stack; re-read the signal after the bar closes.",
            "Stale or partial MT5 data invalidates the bias immediately.",
        ]
    )

    if base.label in (BUY_BIAS, SELL_BIAS) and not supporting:
        base.label = WAIT
        base.direction = DIRECTION_BY_LABEL[WAIT]
        base.warnings.append("Bias downgraded to WAIT because no supporting factor was recorded.")

    return base
