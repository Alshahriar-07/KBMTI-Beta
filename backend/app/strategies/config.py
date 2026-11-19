"""Versioned, frozen configuration for the trend pullback strategy.

Every threshold is explicit so a decision can be reproduced from the snapshot and
the reported `config_version`. Changing a value requires a version bump.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

STRATEGY_ID = "trend_pullback"
STRATEGY_VERSION = "1.0.0"
CONFIG_VERSION = "trend-pullback-config-1.0.0"
SUPPORTED_SYMBOL = "BTCUSDT"
SUPPORTED_TIMEFRAME = "M15"

STRATEGY_DESCRIPTION = (
    "Buy a shallow, structure-intact pullback in an established uptrend after a closed-candle "
    "EMA21 reclaim with improving momentum; mirror for downtrends. Emits no entry, stop or target."
)


class TrendPullbackConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_version: str = STRATEGY_VERSION
    config_version: str = CONFIG_VERSION

    # Price location relative to the fast/slow EMAs, expressed in ATR14 units.
    pullback_zone_atr: float = Field(default=0.35, gt=0.0)
    max_extension_atr: float = Field(default=0.60, gt=0.0)
    max_below_fast_ema_atr: float = Field(default=0.75, gt=0.0)
    max_below_slow_ema_atr: float = Field(default=0.25, gt=0.0)
    min_pullback_depth_atr: float = Field(default=0.25, ge=0.0)

    # Momentum health. A pullback may cool momentum; these bounds define deterioration.
    severe_rsi_long: float = Field(default=30.0, gt=0.0, lt=50.0)
    severe_rsi_short: float = Field(default=70.0, gt=50.0, lt=100.0)
    momentum_roc_deterioration_pct: float = Field(default=0.75, gt=0.0)

    # Structural room and liquidity conflict.
    min_room_atr: float = Field(default=1.0, gt=0.0)
    adverse_sweep_atr: float = Field(default=0.75, gt=0.0)
    adverse_sweep_bars: int = Field(default=8, ge=0)
    structure_lookback_bars: int = Field(default=40, ge=1)

    # Lifetimes, in closed M15 bars from data_as_of.
    candidate_valid_bars: int = Field(default=2, ge=1)
    wait_valid_bars: int = Field(default=1, ge=1)
    no_trade_valid_bars: int = Field(default=1, ge=1)

    def valid_bars(self, decision: str) -> int:
        if decision in {"LONG", "SHORT"}:
            return self.candidate_valid_bars
        if decision == "WAIT":
            return self.wait_valid_bars
        return self.no_trade_valid_bars


DEFAULT_CONFIG = TrendPullbackConfig()
