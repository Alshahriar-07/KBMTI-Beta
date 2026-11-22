"""R-multiple, cost and excursion calculations.

Costs are expressed in quote currency per unit of the instrument, because no position
size exists. A fee of 2.00 and a stop distance of 100 means 0.02R of cost; this is
explicit so a future account-aware sizing layer can replace it without rewriting the
outcome formula.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

ZERO = Decimal("0")


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def risk_per_unit(entry: Decimal, stop: Decimal) -> Decimal:
    return abs(_decimal(entry) - _decimal(stop))


def net_r_multiple(
    *,
    direction: str,
    entry: Decimal,
    stop: Decimal,
    exit_price: Decimal,
    fees: Decimal = ZERO,
    slippage: Decimal = ZERO,
) -> tuple[Decimal | None, Decimal, Decimal]:
    """Return ``(net_r, gross_r, costs_r)``.

    ``net_r`` is ``None`` when the stop equals the entry and risk is zero.
    """

    risk = risk_per_unit(entry, stop)
    if risk <= 0:
        return None, Decimal("0"), Decimal("0")
    e = _decimal(entry)
    x = _decimal(exit_price)
    gross = (x - e) / risk if direction.upper() == "LONG" else (e - x) / risk
    costs = (abs(_decimal(fees)) + abs(_decimal(slippage))) / risk
    return gross - costs, gross, costs


def _price(row: Mapping[str, Any], key: str) -> Decimal:
    return _decimal(row[key])


def excursion_r(
    *,
    direction: str,
    entry: Decimal,
    stop: Decimal,
    candles: Iterable[Mapping[str, Any]],
) -> tuple[Decimal | None, Decimal | None]:
    """Return ``(MFE_R, MAE_R)`` from the recorded holding-window candles.

    LONG MFE uses the highest high, MAE the lowest low; SHORT is mirrored. If no
    candles are available both values are ``None`` rather than zero.
    """

    rows = list(candles)
    risk = risk_per_unit(entry, stop)
    if not rows or risk <= 0:
        return None, None
    e = _decimal(entry)
    if direction.upper() == "LONG":
        highest = max(_price(row, "high") for row in rows)
        lowest = min(_price(row, "low") for row in rows)
        return (highest - e) / risk, (e - lowest) / risk
    highest = max(_price(row, "high") for row in rows)
    lowest = min(_price(row, "low") for row in rows)
    return (e - lowest) / risk, (highest - e) / risk


__all__ = ["excursion_r", "net_r_multiple", "risk_per_unit"]
