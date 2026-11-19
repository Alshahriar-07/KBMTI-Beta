from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import ContainerDep
from app.core.errors import ValidationError
from app.core.timeframes import Timeframe, parse_timeframe
from app.market_data.terminal_discovery import validate_terminal_executable
from app.schemas.models import SettingsPatch, SettingsResponse

router = APIRouter(prefix="/settings", tags=["settings"])

DEFAULT_CHART = {
    "show_ema": True,
    "show_bollinger": True,
    "show_volume": True,
    "show_rsi": True,
    "show_macd": True,
    "show_atr": False,
    "crosshair": True,
}
DEFAULT_DATA = {"candle_retention_days": 30, "tick_retention_days": 7}
DEFAULT_UI = {"sidebar_collapsed": False, "reduced_motion": False, "theme": "dark"}


def _merged(repo, key: str, defaults: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    stored = repo.get(key, {}) or {}
    if not isinstance(stored, dict):
        return dict(defaults)
    return {**defaults, **stored}


def build_settings(container) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    active = container.market.status()
    mt5_status = container.market.mt5_status()
    binance_status = container.market.binance.status()
    repo = container.settings_repo
    provider = str(active.get("provider") or "binance")
    provider_label = str(active.get("provider_label") or ("Binance" if provider == "binance" else "MetaTrader 5"))
    return {
        "symbol": active["selected_symbol"],
        "timeframe": active["timeframe"],
        "candle_limit": container.market.candle_limit,
        "provider": provider,
        "provider_label": provider_label,
        "market": {
            "provider": provider,
            "provider_label": provider_label,
            "selected_symbol": active.get("selected_symbol"),
            "timeframe": active.get("timeframe"),
            "connected": active.get("connected", False),
            "state": active.get("state"),
            "state_label": active.get("state_label"),
            "state_reason": active.get("state_reason"),
            "freshness": active.get("freshness"),
            "freshness_reason": active.get("freshness_reason"),
            "last_successful_update": active.get("last_successful_update"),
            "last_error": active.get("last_error"),
            "ws_connected": active.get("ws_connected"),
            "rest_connected": active.get("rest_connected"),
            "providers": active.get("providers", {}),
        },
        "chart": _merged(repo, "chart", DEFAULT_CHART),
        "data": _merged(repo, "data", DEFAULT_DATA),
        "mt5": {
            "terminal_path": repo.get("mt5.terminal_path") or None,
            "resolved_path": mt5_status.get("resolved_terminal_path"),
            "default_path": mt5_status.get("configured_terminal_path"),
            "detected_paths": mt5_status["terminal_paths"],
            "candidates": mt5_status.get("terminal_candidates", []),
            "state": mt5_status.get("state"),
            "state_label": mt5_status.get("state_label"),
            "state_reason": mt5_status.get("state_reason"),
            "connected": mt5_status.get("connected"),
            "terminal_connected": mt5_status.get("terminal_connected"),
            "broker_connected": mt5_status.get("broker_connected"),
            "terminal": mt5_status.get("terminal", {}),
            "account_available": mt5_status.get("account_available"),
            "connect_timeout_ms": mt5_status.get("connect_timeout_ms"),
            "stale_after_seconds": mt5_status.get("stale_after_seconds"),
            "poll_interval_seconds": mt5_status.get("poll_interval_seconds"),
            "last_error": mt5_status.get("last_error"),
            "freshness": mt5_status.get("freshness"),
            "last_successful_update": mt5_status.get("last_successful_update"),
        },
        "binance": {
            "symbol": repo.get("binance.symbol") or container.settings.binance_symbol or "BTCUSDT",
            "rest_url": container.settings.binance_rest_url,
            "ws_url": container.settings.binance_ws_url,
            "connected": binance_status.get("connected"),
            "ws_connected": binance_status.get("ws_connected"),
            "freshness": binance_status.get("freshness"),
            "last_error": binance_status.get("last_error"),
            "last_successful_update": binance_status.get("last_successful_update"),
        },
        "ui": _merged(repo, "ui", DEFAULT_UI),
        "state": active.get("state"),
        "state_label": active.get("state_label"),
        "state_reason": active.get("state_reason"),
    }


@router.get("", response_model=SettingsResponse)
def get_settings(container: ContainerDep) -> dict:
    return build_settings(container)


@router.patch("", response_model=SettingsResponse)
def patch_settings(payload: SettingsPatch, container: ContainerDep) -> dict:
    repo = container.settings_repo
    if payload.provider is not None:
        container.market.select_provider(payload.provider, connect=True)
    if payload.timeframe is not None:
        try:
            parse_timeframe(payload.timeframe)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        container.market.set_timeframe(payload.timeframe)
    if payload.symbol is not None:
        container.market.select_symbol(payload.symbol)
    if payload.candle_limit is not None:
        container.market.set_candle_limit(payload.candle_limit)
    if payload.chart is not None:
        merged = {**_merged(repo, "chart", DEFAULT_CHART), **payload.chart}
        repo.set("chart", merged)
    if payload.data is not None:
        merged = {**_merged(repo, "data", DEFAULT_DATA), **payload.data}
        for key in ("candle_retention_days", "tick_retention_days"):
            if key in merged:
                try:
                    merged[key] = max(1, min(365, int(merged[key])))
                except (TypeError, ValueError) as exc:
                    raise ValidationError(f"{key} must be an integer number of days.") from exc
        repo.set("data", merged)
    if payload.ui is not None:
        merged_ui = {**_merged(repo, "ui", DEFAULT_UI), **payload.ui}
        theme = merged_ui.get("theme")
        if theme not in {"dark", "light"}:
            raise ValidationError("ui.theme must be either 'dark' or 'light'.")
        repo.set("ui", merged_ui)
    if payload.binance is not None:
        symbol = payload.binance.get("symbol")
        if symbol:
            if container.market.provider_id == "binance":
                container.market.select_symbol(str(symbol))
            else:
                repo.set("binance.symbol", str(symbol).upper())
    if payload.mt5 is not None:
        timeout = payload.mt5.get("connect_timeout_ms")
        if timeout is not None:
            try:
                container.market.set_connect_timeout(int(timeout))
            except (TypeError, ValueError) as exc:
                raise ValidationError("mt5.connect_timeout_ms must be an integer between 1000 and 120000.") from exc
        if "terminal_path" in payload.mt5:
            raw_path = payload.mt5.get("terminal_path")
            if raw_path:
                valid, reason = validate_terminal_executable(str(raw_path))
                if not valid:
                    raise ValidationError(reason or "The selected path is not a MetaTrader 5 terminal.")
                container.market.select_terminal(str(raw_path))
            else:
                container.market.select_terminal(None)
    return build_settings(container)


@router.get("/timeframes", response_model=list[str])
def supported_timeframes() -> list[str]:
    return [timeframe.value for timeframe in Timeframe]
