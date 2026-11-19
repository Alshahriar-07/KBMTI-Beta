"""Supported chart timeframes and their mapping onto MetaTrader 5 constants."""

from __future__ import annotations

from enum import StrEnum

DEFAULT_TIMEFRAME = "M15"


class Timeframe(StrEnum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"


TIMEFRAME_SECONDS: dict[Timeframe, int] = {
    Timeframe.M1: 60,
    Timeframe.M5: 300,
    Timeframe.M15: 900,
    Timeframe.M30: 1800,
    Timeframe.H1: 3600,
    Timeframe.H4: 14400,
    Timeframe.D1: 86400,
}

# Attribute names on the MetaTrader5 module. Resolved with getattr at call time so
# that this module can be imported on machines without the MT5 package.
TIMEFRAME_MT5_CONSTANT: dict[Timeframe, str] = {
    Timeframe.M1: "TIMEFRAME_M1",
    Timeframe.M5: "TIMEFRAME_M5",
    Timeframe.M15: "TIMEFRAME_M15",
    Timeframe.M30: "TIMEFRAME_M30",
    Timeframe.H1: "TIMEFRAME_H1",
    Timeframe.H4: "TIMEFRAME_H4",
    Timeframe.D1: "TIMEFRAME_D1",
}

TIMEFRAME_LABEL: dict[Timeframe, str] = {
    Timeframe.M1: "1 minute",
    Timeframe.M5: "5 minutes",
    Timeframe.M15: "15 minutes",
    Timeframe.M30: "30 minutes",
    Timeframe.H1: "1 hour",
    Timeframe.H4: "4 hours",
    Timeframe.D1: "1 day",
}


def parse_timeframe(value: str | Timeframe | None) -> Timeframe:
    """Return a validated Timeframe, raising ValueError for unsupported input."""

    if isinstance(value, Timeframe):
        return value
    if value is None:
        return Timeframe(DEFAULT_TIMEFRAME)
    try:
        return Timeframe(str(value).strip().upper())
    except ValueError as exc:
        allowed = ", ".join(tf.value for tf in Timeframe)
        raise ValueError(f"Unsupported timeframe '{value}'. Supported values: {allowed}.") from exc
