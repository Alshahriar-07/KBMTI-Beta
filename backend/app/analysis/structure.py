"""Deterministic market structure from closed candles.

Swing points need ``SWING_WINDOW`` closed candles on each side, so the last bars
can never become a swing by definition. A break is only recorded when a closed
candle *closes* beyond a confirmed swing level; a wick alone is not a BOS/CHoCH.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import mean

from app.analysis.contracts import (
    STRUCTURE_VERSION,
    FeatureMeta,
    LevelKind,
    PriceLevel,
    StructureEvent,
    StructureEventType,
    StructureFeature,
    StructureState,
    SwingPoint,
)
from app.analysis.util import utc_from_epoch
from app.market_data.candles import Candle

SWING_WINDOW = 2
MIN_STRUCTURE_BARS = 40
EVENT_LOOKBACK_BARS = 80
LEVEL_LOOKBACK_BARS = 120
LEVEL_CLUSTER_ATR = 0.25
MAX_LEVELS = 8


@dataclass(frozen=True, slots=True)
class _Swing:
    index: int
    time: int
    price: float
    kind: str  # "high" | "low"


def _meta(calculated_at: datetime, source: str, *, valid: bool, reason: str | None = None) -> FeatureMeta:
    return FeatureMeta(
        version=STRUCTURE_VERSION,
        source=source,
        calculated_at=calculated_at,
        valid=valid,
        reason=reason,
    )


def find_swings(candles: list[Candle], window: int = SWING_WINDOW) -> list[_Swing]:
    """Return confirmed swing highs/lows using only the supplied closed candles."""

    swings: list[_Swing] = []
    if len(candles) < window * 2 + 1:
        return swings
    for index in range(window, len(candles) - window):
        candle = candles[index]
        neighbours = candles[index - window : index] + candles[index + 1 : index + 1 + window]
        if all(candle.high > other.high for other in neighbours):
            swings.append(_Swing(index=index, time=int(candle.time), price=float(candle.high), kind="high"))
        if all(candle.low < other.low for other in neighbours):
            swings.append(_Swing(index=index, time=int(candle.time), price=float(candle.low), kind="low"))
    swings.sort(key=lambda item: (item.index, item.kind))
    return swings


def _trend_from_swings(swings: list[_Swing]) -> StructureState:
    highs = [swing for swing in swings if swing.kind == "high"][-2:]
    lows = [swing for swing in swings if swing.kind == "low"][-2:]
    if len(highs) < 2 or len(lows) < 2:
        return StructureState.INSUFFICIENT_DATA
    higher_high = highs[1].price > highs[0].price
    higher_low = lows[1].price > lows[0].price
    if higher_high and higher_low:
        return StructureState.UPTREND
    if not higher_high and not higher_low:
        return StructureState.DOWNTREND
    return StructureState.RANGING


def insufficient_structure(calculated_at: datetime, source: str, reason: str) -> StructureFeature:
    return StructureFeature(
        meta=_meta(calculated_at, source, valid=False, reason=reason),
        state=StructureState.INSUFFICIENT_DATA,
    )


def _swing_events(swings: list[_Swing]) -> list[StructureEvent]:
    events: list[StructureEvent] = []
    last_high: _Swing | None = None
    last_low: _Swing | None = None
    for swing in swings:
        if swing.kind == "high":
            if last_high is not None:
                event_type = StructureEventType.HH if swing.price > last_high.price else StructureEventType.LH
                events.append(
                    StructureEvent(
                        type=event_type,
                        price=swing.price,
                        candle_time=utc_from_epoch(swing.time),
                        confirmed=True,
                        evidence=[f"swing:high:{swing.time}", f"previous_swing:high:{last_high.time}"],
                    )
                )
            last_high = swing
        else:
            if last_low is not None:
                event_type = StructureEventType.HL if swing.price > last_low.price else StructureEventType.LL
                events.append(
                    StructureEvent(
                        type=event_type,
                        price=swing.price,
                        candle_time=utc_from_epoch(swing.time),
                        confirmed=True,
                        evidence=[f"swing:low:{swing.time}", f"previous_swing:low:{last_low.time}"],
                    )
                )
            last_low = swing
    return events


def _break_events(
    candles: list[Candle],
    swings: list[_Swing],
) -> list[tuple[int, StructureEvent]]:
    """Scan closed candles for confirmed BOS/CHoCH events.

    Returns ``(bar_index, event)`` pairs so the caller can apply a lookback window.
    """

    events: list[tuple[int, StructureEvent]] = []
    broken_highs: set[int] = set()
    broken_lows: set[int] = set()
    for index in range(1, len(candles)):
        confirmed = [swing for swing in swings if swing.index + SWING_WINDOW <= index]
        if len(confirmed) < 4:
            continue
        confirmed_highs = [swing for swing in confirmed if swing.kind == "high"]
        confirmed_lows = [swing for swing in confirmed if swing.kind == "low"]
        if not confirmed_highs or not confirmed_lows:
            continue
        last_high = next(
            (swing for swing in reversed(confirmed_highs) if swing.index not in broken_highs),
            None,
        )
        last_low = next(
            (swing for swing in reversed(confirmed_lows) if swing.index not in broken_lows),
            None,
        )
        if last_high is None or last_low is None:
            continue
        state = _trend_from_swings(confirmed)
        close = float(candles[index].close)
        candle_time = utc_from_epoch(candles[index].time)
        if state is StructureState.UPTREND and close > last_high.price:
            events.append(
                (
                    index,
                    StructureEvent(
                        type=StructureEventType.BOS_UP,
                        price=close,
                        candle_time=candle_time,
                        confirmed=True,
                        broken_level=last_high.price,
                        evidence=[f"candle:{candles[index].time}", f"level:high:{last_high.time}"],
                    ),
                )
            )
            broken_highs.add(last_high.index)
        elif state is StructureState.DOWNTREND and close > last_high.price:
            events.append(
                (
                    index,
                    StructureEvent(
                        type=StructureEventType.CHOCH_UP,
                        price=close,
                        candle_time=candle_time,
                        confirmed=True,
                        broken_level=last_high.price,
                        evidence=[f"candle:{candles[index].time}", f"level:high:{last_high.time}"],
                    ),
                )
            )
            broken_highs.add(last_high.index)
        elif state is StructureState.DOWNTREND and close < last_low.price:
            events.append(
                (
                    index,
                    StructureEvent(
                        type=StructureEventType.BOS_DOWN,
                        price=close,
                        candle_time=candle_time,
                        confirmed=True,
                        broken_level=last_low.price,
                        evidence=[f"candle:{candles[index].time}", f"level:low:{last_low.time}"],
                    ),
                )
            )
            broken_lows.add(last_low.index)
        elif state is StructureState.UPTREND and close < last_low.price:
            events.append(
                (
                    index,
                    StructureEvent(
                        type=StructureEventType.CHOCH_DOWN,
                        price=close,
                        candle_time=candle_time,
                        confirmed=True,
                        broken_level=last_low.price,
                        evidence=[f"candle:{candles[index].time}", f"level:low:{last_low.time}"],
                    ),
                )
            )
            broken_lows.add(last_low.index)
    return events


def _cluster_levels(
    swings: list[_Swing],
    *,
    last_close: float,
    tolerance: float,
    last_time: int,
) -> list[PriceLevel]:
    cutoff = last_time - LEVEL_LOOKBACK_BARS * 900
    recent = [swing for swing in swings if swing.time >= cutoff]
    levels: list[PriceLevel] = []
    for kind, level_kind, source in (
        ("high", LevelKind.RESISTANCE, "swing_high"),
        ("low", LevelKind.SUPPORT, "swing_low"),
    ):
        items = sorted((swing for swing in recent if swing.kind == kind), key=lambda swing: swing.price)
        clusters: list[list[_Swing]] = []
        for item in items:
            if clusters and abs(item.price - mean(swing.price for swing in clusters[-1])) <= tolerance:
                clusters[-1].append(item)
            else:
                clusters.append([item])
        for cluster in clusters:
            levels.append(
                PriceLevel(
                    kind=level_kind,
                    price=round(mean(swing.price for swing in cluster), 8),
                    touches=len(cluster),
                    first_time=utc_from_epoch(min(swing.time for swing in cluster)),
                    last_time=utc_from_epoch(max(swing.time for swing in cluster)),
                    source=source,
                    evidence=[f"swing:{kind}:{swing.time}" for swing in cluster],
                )
            )
    levels.sort(key=lambda level: (level.touches, -abs(level.price - last_close)), reverse=True)
    return levels[:MAX_LEVELS]


def evaluate_structure(
    candles: list[Candle],
    *,
    atr14: float | None,
    calculated_at: datetime,
    source: str,
) -> StructureFeature:
    if len(candles) < MIN_STRUCTURE_BARS:
        return insufficient_structure(
            calculated_at,
            source,
            f"At least {MIN_STRUCTURE_BARS} closed candles are required for structure analysis.",
        )

    swings = find_swings(candles)
    if len(swings) < 4:
        return insufficient_structure(calculated_at, source, "Not enough confirmed swing points to describe structure.")

    state = _trend_from_swings(swings)
    label_events = _swing_events(swings)
    breaks = _break_events(candles, swings)
    visible_breaks = [
        event for index, event in breaks if index >= len(candles) - EVENT_LOOKBACK_BARS
    ]
    events = label_events + visible_breaks
    events.sort(key=lambda event: event.candle_time)

    state_events = [event for event in events if event.type in {StructureEventType.CHOCH_UP, StructureEventType.CHOCH_DOWN}]
    if state_events:
        last_character = state_events[-1].type
        if last_character is StructureEventType.CHOCH_DOWN and state is StructureState.UPTREND:
            state = StructureState.TRANSITION
        elif last_character is StructureEventType.CHOCH_UP and state is StructureState.DOWNTREND:
            state = StructureState.TRANSITION

    atr = atr14 if atr14 and atr14 > 0 else max(float(candles[-1].close) * 0.001, 0.01)
    tolerance = max(atr * LEVEL_CLUSTER_ATR, float(candles[-1].close) * 0.0005)
    levels = _cluster_levels(
        swings,
        last_close=float(candles[-1].close),
        tolerance=tolerance,
        last_time=int(candles[-1].time),
    )

    bos = [event for event in events if event.type in {StructureEventType.BOS_UP, StructureEventType.BOS_DOWN}]
    choch = [event for event in events if event.type in {StructureEventType.CHOCH_UP, StructureEventType.CHOCH_DOWN}]

    return StructureFeature(
        meta=_meta(calculated_at, source, valid=True),
        state=state,
        swings=[
            SwingPoint(
                kind=swing.kind,
                price=round(swing.price, 8),
                time=utc_from_epoch(swing.time),
                index=swing.index,
                evidence=[f"swing:{swing.kind}:{swing.time}"],
            )
            for swing in swings[-16:]
        ],
        events=events[-24:],
        levels=levels,
        last_bos=bos[-1] if bos else None,
        last_choch=choch[-1] if choch else None,
        evidence=[f"structure:{state.value.lower()}"]
        + [f"event:{event.type.value}:{int(event.candle_time.timestamp())}" for event in events[-4:]],
    )
