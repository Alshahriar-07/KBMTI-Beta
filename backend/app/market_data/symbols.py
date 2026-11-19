"""Broker-agnostic BTC symbol discovery.

Brokers expose the same instrument under suffixes such as BTCUSD, BTCUSDm,
BTCUSD., BTCUSD_i or XBTUSD. Discovery ranks candidates instead of assuming one
name, and the user always confirms the final selection in the UI.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

BTC_TOKEN = re.compile(r"BTC|XBT|BITCOIN", re.IGNORECASE)
USD_TOKEN = re.compile(r"USD|USDT|USDC", re.IGNORECASE)


def _score_symbol(info: dict[str, Any]) -> tuple[int, str] | None:
    name = str(info.get("name") or "").upper()
    description = str(info.get("description") or "")
    path = str(info.get("path") or "")
    haystack = f"{name} {description} {path}"

    if not BTC_TOKEN.search(haystack):
        return None

    if name == "BTCUSD":
        score, reason = 100, "Exact BTCUSD match"
    elif name.startswith("BTCUSD"):
        score, reason = 94, "BTCUSD with broker suffix"
    elif name.startswith("BTC") and USD_TOKEN.search(name):
        score, reason = 92, "BTC pair with USD quote"
    elif name.startswith("XBT") and USD_TOKEN.search(name):
        score, reason = 88, "XBT (alternative BTC ticker) pair"
    elif "BTC" in name:
        score, reason = 84, "BTC symbol with broker-specific format"
    elif "XBT" in name:
        score, reason = 78, "XBT symbol with broker-specific format"
    else:
        score, reason = 64, "Bitcoin mentioned in symbol description or group"

    if "CRYPTO" in path.upper() or "CRYPTOCURRENC" in path.upper():
        score = min(100, score + 2)
    if info.get("trade_mode") == 0:
        score -= 15
        reason += " · trading disabled"
    if info.get("visible"):
        score += 1

    return score, reason


def discover_btc_symbols(symbols: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return BTC-like broker symbols ranked by likely relevance."""

    results: list[dict[str, Any]] = []
    for info in symbols:
        scored = _score_symbol(info)
        if scored is None:
            continue
        score, reason = scored
        enriched = dict(info)
        enriched["match_score"] = score
        enriched["match_reason"] = reason
        results.append(enriched)

    results.sort(key=lambda item: (-int(item["match_score"]), str(item.get("name") or "")))
    for index, item in enumerate(results):
        item["recommended"] = index == 0
    return results


def is_btc_like(symbol: str, description: str = "", path: str = "") -> bool:
    return bool(BTC_TOKEN.search(f"{symbol} {description} {path}"))


def pick_default_symbol(candidates: list[dict[str, Any]], preferred: str | None = None) -> str | None:
    """Suggest (never silently apply) a default candidate for the picker."""

    if not candidates:
        return None
    if preferred:
        for candidate in candidates:
            if candidate.get("name") == preferred:
                return preferred
    return str(candidates[0].get("name")) or None
