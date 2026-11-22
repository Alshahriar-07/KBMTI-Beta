"""Chronological, cost-aware backtesting of the frozen strategy and planner.

No parameter is fitted. Each decision uses only candles closed at that point. The
simulation enters at the suggested entry if a later candle trades through the zone,
exits at TP1 or the structural stop, and reports the untouched test split separately.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.analysis.context import MarketContextBuilder
from app.analysis.contracts import SCOPE_TIMEFRAME_SECONDS
from app.learning.contracts import (
    BacktestConfig,
    BacktestMetrics,
    BacktestReport,
    BacktestTrade,
    SplitName,
)
from app.market_data.candles import Candle, raw_to_candle
from app.risk.engine import assess_risk
from app.strategies.contracts import ConfirmationStatus, StrategyDecision
from app.strategies.trend_pullback import evaluate_trend_pullback
from app.trade_planning.planner import build_geometry


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _drawdown(values: list[float]) -> float | None:
    if not values:
        return None
    cumulative = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        worst = min(worst, cumulative - peak)
    return round(worst, 6)


def _group_metrics(trades: list[BacktestTrade], mode: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[BacktestTrade]] = {}
    for trade in trades:
        if trade.net_r is None:
            continue
        key = trade.direction if mode == "direction" else trade.regime
        groups.setdefault(key, []).append(trade)
    result: dict[str, dict[str, Any]] = {}
    for key, rows in sorted(groups.items()):
        values = [float(row.net_r) for row in rows if row.net_r is not None]
        wins = [value for value in values if value > 0.05]
        losses = [value for value in values if value < -0.05]
        result[key] = {
            "trades": len(values),
            "win_rate": round(len(wins) / len(values), 4) if values else None,
            "expectancy_r": round(sum(values) / len(values), 6) if values else None,
            "profit_factor": round(sum(wins) / abs(sum(losses)), 4) if losses else None,
        }
    return result


def metrics_from_trades(trades: list[BacktestTrade]) -> BacktestMetrics:
    executed = [trade for trade in trades if trade.net_r is not None]
    values = [float(trade.net_r) for trade in executed if trade.net_r is not None]
    wins = [value for value in values if value > 0.05]
    losses = [value for value in values if value < -0.05]
    breakeven = len(values) - len(wins) - len(losses)
    total = sum(values) if values else None
    return BacktestMetrics(
        trades=len(values),
        wins=len(wins),
        losses=len(losses),
        breakeven=breakeven,
        win_rate=round(len(wins) / len(values), 4) if values else None,
        expectancy_r=round(sum(values) / len(values), 6) if values else None,
        profit_factor=round(sum(wins) / abs(sum(losses)), 4) if losses else None,
        max_drawdown_r=_drawdown(values),
        average_win_r=round(sum(wins) / len(wins), 6) if wins else None,
        average_loss_r=round(sum(losses) / len(losses), 6) if losses else None,
        total_r=round(total, 6) if total is not None else None,
        by_regime=_group_metrics(executed, "regime"),
        by_direction=_group_metrics(executed, "direction"),
        sample_warning=(
            "Fewer than 30 executed trades; the result is descriptive and cannot establish an edge."
            if 0 < len(values) < 30
            else None
        ),
    )


class Backtester:
    def run(self, candles: list[dict[str, Any]], *, config: BacktestConfig | None = None) -> BacktestReport:
        cfg = config or BacktestConfig()
        ordered = sorted(
            [
                raw_to_candle(row)
                for row in candles
                if all(row.get(key) is not None for key in ("time", "open", "high", "low", "close"))
            ],
            key=lambda item: int(item.time),
        )
        if len(ordered) < cfg.window_bars + 20:
            raise ValueError(
                f"backtest needs at least {cfg.window_bars + 20} closed candles, received {len(ordered)}"
            )
        times = [int(candle.time) for candle in ordered]
        if len(set(times)) != len(times):
            raise ValueError("duplicate candle timestamps; backtest refused")

        splits = self._splits(len(ordered), cfg)
        trades: list[BacktestTrade] = []
        builder = MarketContextBuilder(stale_after_seconds=10**9)
        i = cfg.window_bars - 1
        while i < len(ordered) - 1:
            split = splits[i]
            if split is SplitName.PURGED:
                i += 1
                continue
            window = ordered[max(0, i - cfg.window_bars + 1) : i + 1]
            close_time = datetime.fromtimestamp(int(window[-1].time) + SCOPE_TIMEFRAME_SECONDS, UTC)
            try:
                snapshot = builder.build(
                    symbol=cfg.symbol,
                    timeframe=cfg.timeframe,
                    candles=window,
                    provider="backtest",
                    source="stored_candles",
                    fetched_at=close_time,
                    request_id=uuid.uuid4().hex,
                    fetch_notes=["chronological backtest; only candles closed at this point were supplied"],
                )
                evaluation = evaluate_trend_pullback(snapshot, evaluated_at=close_time)
            except Exception:
                i += 1
                continue
            if evaluation.decision not in {StrategyDecision.LONG, StrategyDecision.SHORT}:
                i += 1
                continue
            if evaluation.confirmation_status is not ConfirmationStatus.CONFIRMED:
                i += 1
                continue
            geometry_result = build_geometry(evaluation=evaluation, snapshot=snapshot)
            geometry = geometry_result.geometry
            if geometry is None:
                i += 1
                continue
            risk = assess_risk(
                direction=geometry.direction,
                entry=geometry.suggested_entry,
                stop=geometry.stop_loss,
                targets=[target.price for target in geometry.targets],
                target_conflict=geometry.target_conflict,
                atr=geometry.atr,
                snapshot=snapshot,
                evaluation=evaluation,
            )
            if not risk.passed:
                i += 1
                continue

            trade, consumed = self._simulate(
                ordered=ordered,
                splits=splits,
                index=i,
                config=cfg,
                direction=geometry.direction.value,
                entry=float(geometry.suggested_entry),
                stop=float(geometry.stop_loss),
                target=float(geometry.targets[0].price),
                regime=snapshot.regime.state.value,
                split=split,
            )
            trades.append(trade)
            i = max(i + 1, consumed)

        window_report = self._window_ranges(len(ordered), cfg)
        by_split: dict[str, BacktestMetrics] = {}
        labels = {
            "train": SplitName.TRAIN,
            "validation": SplitName.VALIDATION,
            "test": SplitName.TEST,
        }
        for label, split_name in labels.items():
            subset = [trade for trade in trades if trade.split == split_name.value]
            by_split[label] = metrics_from_trades(subset)
        return BacktestReport(
            backtest_id=f"bt_{uuid.uuid4().hex[:20]}",
            created_at=datetime.now(UTC),
            status="COMPLETE",
            config=cfg,
            windows={
                **window_report,
                "splits": {
                    label: by_split[label].model_dump(mode="json") for label in by_split
                },
            },
            metrics=by_split["test"],
            overall=metrics_from_trades(trades),
            trades=trades,
            warnings=[
                "Full-exit simulation at TP1; no partial exits or breakeven management are assumed.",
                "Both stop and target inside one candle resolves to the stop (pessimistic).",
                "Entry requires a later candle to trade inside the plan zone; missed setups are not losses.",
                "Costs are charged in basis points on entry and exit; no funding or swap is modelled.",
                "The strategy gate is PENDING; these results are research, not validation.",
            ],
            evaluation_scope="Frozen rules; no parameter fitting; chronological partitions.",
            sealed_test_note=(
                "The test partition was not used for parameter selection or threshold changes. "
                "It remains one historical sample, not a live-trading guarantee."
            ),
        )

    def _simulate(
        self,
        *,
        ordered: list[Candle],
        splits: list[SplitName],
        index: int,
        config: BacktestConfig,
        direction: str,
        entry: float,
        stop: float,
        target: float,
        regime: str,
        split: SplitName,
    ) -> tuple[BacktestTrade, int]:
        risk = abs(entry - stop)
        cost_bps = config.fee_bps + config.spread_bps / 2.0 + config.slippage_bps
        entry_adjusted = entry * (1 + cost_bps / 10_000.0 if direction == "LONG" else 1 - cost_bps / 10_000.0)
        signal_time = datetime.fromtimestamp(int(ordered[index].time), UTC).isoformat()
        end = min(len(ordered) - 1, index + config.max_hold_bars)
        for cursor in range(index + 1, end + 1):
            if splits[cursor] is not split:
                break
            candle = ordered[cursor]
            low, high = float(candle.low), float(candle.high)
            touched = low <= entry <= high
            if not touched:
                continue
            entry_time = datetime.fromtimestamp(int(candle.time), UTC).isoformat()
            stop_hit = low <= stop if direction == "LONG" else high >= stop
            target_hit = high >= target if direction == "LONG" else low <= target
            exit_reason = "STOP" if stop_hit else "TP1" if target_hit else None
            exit_price = stop if stop_hit else target if target_hit else None
            exit_index = cursor
            if exit_reason is None:
                for later in range(cursor + 1, end + 1):
                    if splits[later] is not split:
                        break
                    row = ordered[later]
                    low, high = float(row.low), float(row.high)
                    if (low <= stop if direction == "LONG" else high >= stop):
                        exit_reason, exit_price, exit_index = "STOP", stop, later
                        break
                    if (high >= target if direction == "LONG" else low <= target):
                        exit_reason, exit_price, exit_index = "TP1", target, later
                        break
                if exit_reason is None:
                    exit_reason, exit_price, exit_index = "TIME", float(ordered[end].close), end
            assert exit_price is not None
            exit_adjusted = exit_price * (
                1 - cost_bps / 10_000.0 if direction == "LONG" else 1 + cost_bps / 10_000.0
            )
            gross = (exit_price - entry) / risk if direction == "LONG" else (entry - exit_price) / risk
            net = (
                (exit_adjusted - entry_adjusted) / risk
                if direction == "LONG"
                else (entry_adjusted - exit_adjusted) / risk
            )
            excursion_rows = ordered[cursor : exit_index + 1]
            if direction == "LONG":
                mfe = (max(float(row.high) for row in excursion_rows) - entry_adjusted) / risk
                mae = (entry_adjusted - min(float(row.low) for row in excursion_rows)) / risk
            else:
                mfe = (entry_adjusted - min(float(row.low) for row in excursion_rows)) / risk
                mae = (max(float(row.high) for row in excursion_rows) - entry_adjusted) / risk
            return (
                BacktestTrade(
                    direction=direction,
                    signal_time=signal_time,
                    entry_time=entry_time,
                    entry=round(entry_adjusted, 8),
                    stop=round(stop, 8),
                    target=round(target, 8),
                    exit_time=datetime.fromtimestamp(int(ordered[exit_index].time), UTC).isoformat(),
                    exit_price=round(exit_adjusted, 8),
                    exit_reason=exit_reason,
                    gross_r=round(gross, 6),
                    net_r=round(net, 6),
                    mfe_r=round(mfe, 6),
                    mae_r=round(mae, 6),
                    regime=regime,
                    split=split.value,
                ),
                exit_index + 1,
            )
        return (
            BacktestTrade(
                direction=direction,
                signal_time=signal_time,
                exit_reason="ENTRY_MISSED",
                regime=regime,
                split=split.value,
            ),
            index + 1,
        )

    def _splits(self, total: int, config: BacktestConfig) -> list[SplitName]:
        gap = config.purge_bars + config.embargo_bars
        usable = total - 2 * gap
        if usable < 30:
            raise ValueError("purge/embargo leave too few candles")
        train_end = int(usable * config.train_fraction)
        validation_size = int(usable * config.validation_fraction)
        validation_start = train_end + gap
        validation_end = validation_start + validation_size
        test_start = validation_end + gap
        splits: list[SplitName] = []
        for index in range(total):
            if index < train_end:
                splits.append(SplitName.TRAIN)
            elif index < validation_start:
                splits.append(SplitName.PURGED)
            elif index < validation_end:
                splits.append(SplitName.VALIDATION)
            elif index < test_start:
                splits.append(SplitName.PURGED)
            else:
                splits.append(SplitName.TEST)
        return splits

    def _window_ranges(self, total: int, config: BacktestConfig) -> dict[str, Any]:
        splits = self._splits(total, config)
        ranges: dict[str, Any] = {}
        for label in (SplitName.TRAIN, SplitName.VALIDATION, SplitName.TEST, SplitName.PURGED):
            indices = [index for index, split in enumerate(splits) if split is label]
            ranges[label.value.lower()] = {
                "start": indices[0] if indices else None,
                "end": (indices[-1] + 1) if indices else None,
                "count": len(indices),
            }
        return ranges


__all__ = ["Backtester", "metrics_from_trades"]
