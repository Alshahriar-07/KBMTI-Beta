"""Strict, defensive wrapper around the official MetaTrader5 Python package.

The wrapper owns one IPC session and never silently attaches to a different
terminal than the one it was given. Initialization is only reported as connected
after all of the following are verified:

* ``mt5.initialize`` returned True,
* ``terminal_info()`` exists,
* ``terminal_info().connected`` is True,
* ``account_info()`` is accessible.

Every call is serialized by a re-entrant lock because the MetaTrader5 IPC layer is
not thread-safe. The package is imported lazily so the backend and its tests run
on machines without MetaTrader 5 installed.
"""

from __future__ import annotations

import importlib
import logging
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.errors import (
    MT5AccountUnavailableError,
    MT5BrokerDisconnectedError,
    MT5DataError,
    MT5DisconnectedError,
    MT5HistoryUnavailableError,
    MT5NotInstalledError,
    MT5SymbolUnavailableError,
    MT5TerminalNotFoundError,
    MT5TickUnavailableError,
)
from app.core.timeframes import TIMEFRAME_MT5_CONSTANT, Timeframe
from app.market_data.terminal_discovery import (
    TerminalCandidate,
    discover_terminals,
    normalize_path,
    validate_terminal_executable,
)

logger = logging.getLogger(__name__)

DEFAULT_INIT_TIMEOUT_MS = 15_000
ACCOUNT_INFO_RETRIES = 6
ACCOUNT_INFO_RETRY_SECONDS = 0.25

# Codes that mean the terminal or the IPC bridge is no longer usable.
DISCONNECT_CODES = frozenset(
    {-6, -7, -10003, -10004, -10005, -10006, -10007, -10008, -10009, -10010, -10013, -10014}
)
BROKER_CODES = frozenset({-6, -7, -10009, -10013})

MT5_ERROR_HINTS: dict[int, str] = {
    -1: "Unexpected MetaTrader 5 error.",
    -2: "Invalid terminal path.",
    -3: "The terminal could not be launched.",
    -4: "Symbol not found on the broker server.",
    -5: "Timed out waiting for the terminal response.",
    -6: "Authorization failed. Log in to the MetaTrader 5 terminal first.",
    -7: "The terminal is not connected to the broker server.",
    -8: "The terminal is not authorized to run the Python API.",
    -10000: "Unexpected terminal error.",
    -10001: "Invalid request arguments.",
    -10002: "IPC timeout while waiting for the terminal.",
    -10003: "The MetaTrader 5 terminal is not running.",
    -10004: "Could not establish the MetaTrader 5 IPC connection.",
    -10005: "The terminal did not answer the IPC handshake.",
    -10006: "Request rejected by the terminal.",
    -10007: "The MetaTrader 5 terminal has not been initialized.",
    -10008: "The terminal is already running under a different account.",
    -10009: "The terminal is not connected to the trade server.",
    -10010: "The automated interface request was rejected by the terminal.",
    -10011: "The terminal has not enabled the Python bridge.",
    -10012: "The terminal's automated interface settings rejected the request.",
    -10013: "The terminal is offline.",
    -10014: "The terminal's automated interface is disabled in settings.",
}

TRADE_MODE_LABEL: dict[int, str] = {
    0: "Disabled",
    1: "Long only",
    2: "Short only",
    3: "Close only",
    4: "Full access",
}


@dataclass(frozen=True, slots=True)
class MT5Error:
    code: int | None
    description: str | None
    message: str
    operation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "description": self.description,
            "message": self.message,
            "operation": self.operation,
        }


def describe_error(code: int | None, description: str | None = None) -> str:
    if code is None and not description:
        return "Unknown MetaTrader 5 error."
    hint = MT5_ERROR_HINTS.get(int(code)) if code is not None else None
    if hint and description:
        return f"{hint} (code {code}: {description})"
    if hint:
        return f"{hint} (code {code})"
    return description or f"MetaTrader 5 error code {code}."


def _safe_getattr(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name, default)
    except Exception:  # pragma: no cover - MT5 objects are plain structs
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _terminal_info_to_dict(info: Any) -> dict[str, Any]:
    if info is None:
        return {}
    fields = (
        "name",
        "company",
        "path",
        "data_path",
        "common_data_path",
        "build",
        "language",
        "maxbars",
        "connected",
        "trade_allowed",
        "dlls_allowed",
        "community_connected",
        "ping_last",
    )
    return {field: _safe_getattr(info, field) for field in fields if _safe_getattr(info, field) is not None}


def _account_info_to_dict(info: Any) -> dict[str, Any]:
    """Account facts that are useful for diagnostics, without balances or PII."""

    if info is None:
        return {}
    login = str(_safe_getattr(info, "login", "") or "")
    masked_login = f"{'*' * max(0, len(login) - 4)}{login[-4:]}" if login else None
    trade_mode = _safe_getattr(info, "trade_mode", None)
    return {
        "available": True,
        "login_masked": masked_login,
        "server": _safe_getattr(info, "server", None),
        "company": _safe_getattr(info, "company", None),
        "currency": _safe_getattr(info, "currency", None),
        "leverage": _safe_getattr(info, "leverage", None),
        "trade_allowed": _safe_getattr(info, "trade_allowed", None),
        "trade_mode": trade_mode,
        "trade_mode_label": TRADE_MODE_LABEL.get(int(trade_mode)) if trade_mode is not None else None,
    }


def _symbol_info_to_dict(info: Any) -> dict[str, Any]:
    if info is None:
        return {}
    trade_mode = _safe_getattr(info, "trade_mode", None)
    return {
        "name": _safe_getattr(info, "name", ""),
        "description": _safe_getattr(info, "description", "") or "",
        "path": _safe_getattr(info, "path", "") or "",
        "digits": _as_int(_safe_getattr(info, "digits", 0)),
        "point": _as_float(_safe_getattr(info, "point", 0.0)),
        "spread": _as_int(_safe_getattr(info, "spread", 0)),
        "trade_mode": int(trade_mode) if trade_mode is not None else None,
        "trade_mode_label": TRADE_MODE_LABEL.get(int(trade_mode)) if trade_mode is not None else None,
        "currency_base": _safe_getattr(info, "currency_base", "") or "",
        "currency_profit": _safe_getattr(info, "currency_profit", "") or "",
        "visible": bool(_safe_getattr(info, "visible", False)),
        "volume_min": _as_float(_safe_getattr(info, "volume_min", 0.0)),
        "volume_step": _as_float(_safe_getattr(info, "volume_step", 0.0)),
        "bid": _as_float(_safe_getattr(info, "bid", 0.0)),
        "ask": _as_float(_safe_getattr(info, "ask", 0.0)),
    }


def _tick_to_dict(tick: Any) -> dict[str, Any]:
    return {
        "time": _as_int(_safe_getattr(tick, "time", 0)),
        "time_msc": _as_int(_safe_getattr(tick, "time_msc", 0)),
        "bid": _as_float(_safe_getattr(tick, "bid", 0.0)),
        "ask": _as_float(_safe_getattr(tick, "ask", 0.0)),
        "last": _as_float(_safe_getattr(tick, "last", 0.0)),
        "volume": _as_int(_safe_getattr(tick, "volume", 0)),
        "flags": _as_int(_safe_getattr(tick, "flags", 0)),
    }


def _records_to_rows(records: Any) -> list[dict[str, Any]]:
    if records is None:
        return []
    if isinstance(records, list):
        return list(records)
    names = getattr(getattr(records, "dtype", None), "names", None)
    if names:
        return [
            {name: record[name].item() if hasattr(record[name], "item") else record[name] for name in names}
            for record in records
        ]
    return list(records)


class MT5Gateway:
    """Read-only access to exactly one locally installed MetaTrader 5 terminal."""

    def __init__(
        self,
        module: Any | None = None,
        terminal_path: str | Path | None = None,
        timeout_ms: int = DEFAULT_INIT_TIMEOUT_MS,
    ) -> None:
        self._module = module
        self._explicit_module = module is not None
        self._lock = threading.RLock()
        self._connected = False
        self._ipc_connected = False
        self._broker_connected = False
        self._account_available = False
        self._last_error: MT5Error | None = None
        self._terminal_path = normalize_path(terminal_path)
        self._timeout_ms = max(1_000, min(120_000, int(timeout_ms or DEFAULT_INIT_TIMEOUT_MS)))
        self._terminal_info: dict[str, Any] = {}
        self._account_info: dict[str, Any] = {}

    # ------------------------------------------------------------------ setup
    @property
    def module(self) -> Any:
        if self._module is None:
            try:
                self._module = importlib.import_module("MetaTrader5")
            except ImportError as exc:  # pragma: no cover - depends on host
                raise MT5NotInstalledError(
                    "The MetaTrader5 Python package is not installed. "
                    "Install it with: python -m pip install MetaTrader5"
                ) from exc
        return self._module

    @property
    def terminal_path(self) -> str | None:
        return self._terminal_path

    @property
    def timeout_ms(self) -> int:
        return self._timeout_ms

    def set_terminal_path(self, path: str | Path | None) -> None:
        with self._lock:
            self._terminal_path = normalize_path(path)

    def set_timeout_ms(self, timeout_ms: int) -> int:
        with self._lock:
            self._timeout_ms = max(1_000, min(120_000, int(timeout_ms)))
            return self._timeout_ms

    def package_available(self) -> bool:
        try:
            return self.module is not None
        except MT5NotInstalledError:
            return False

    def package_version(self) -> str | None:
        try:
            return str(getattr(self.module, "__version__", "") or "") or None
        except MT5NotInstalledError:
            return None

    @property
    def last_error(self) -> str | None:
        return self._last_error.message if self._last_error else None

    @property
    def last_error_detail(self) -> dict[str, Any] | None:
        return self._last_error.to_dict() if self._last_error else None

    def _read_last_error(self, operation: str | None = None) -> MT5Error | None:
        try:
            code, description = self.module.last_error()
        except Exception:  # pragma: no cover - defensive
            return None
        if code in (0, None):
            return None
        error = MT5Error(
            code=int(code),
            description=str(description) if description else None,
            message=describe_error(code, description),
            operation=operation,
        )
        self._last_error = error
        return error

    def _capture_error(self, operation: str, fallback: str) -> MT5Error:
        error = self._read_last_error(operation)
        if error:
            return error
        error = MT5Error(code=None, description=None, message=fallback, operation=operation)
        self._last_error = error
        return error

    def _mark_down(self, message: str, *, code: int | None = None, description: str | None = None, operation: str | None = None) -> None:
        self._connected = False
        self._broker_connected = False
        self._account_available = False
        self._last_error = MT5Error(code=code, description=description, message=message, operation=operation)

    @staticmethod
    def _details(error: MT5Error) -> dict[str, Any]:
        return error.to_dict()

    def _is_disconnect(self, error: MT5Error | None) -> bool:
        return bool(error and error.code in DISCONNECT_CODES)

    def detect_terminal_paths(self) -> list[str]:
        return [candidate.path for candidate in self.terminal_candidates()]

    def terminal_candidates(self) -> list[TerminalCandidate]:
        return discover_terminals([self._terminal_path] if self._terminal_path else [])

    # ------------------------------------------------------------- connection
    def initialize(self, path: str | None = None, timeout_ms: int | None = None) -> dict[str, Any]:
        with self._lock:
            if self._connected:
                health = self.health()
                if health.get("connected"):
                    return self._terminal_info
                self.shutdown()

            target = normalize_path(path or self._terminal_path)
            if target:
                valid, reason = validate_terminal_executable(target)
                if not valid:
                    self._last_error = MT5Error(
                        code=-2,
                        description=reason,
                        message=reason or "Invalid terminal path.",
                        operation="initialize",
                    )
                    raise MT5TerminalNotFoundError(reason or "Invalid terminal path.", {"path": target})

            module = self.module
            kwargs: dict[str, Any] = {"timeout": int(timeout_ms or self._timeout_ms)}
            if target:
                kwargs["path"] = target
            try:
                initialized = module.initialize(**kwargs)
            except Exception as exc:  # pragma: no cover - MT5 raises rarely
                message = f"MetaTrader 5 initialization failed: {exc}"
                self._last_error = MT5Error(code=None, description=str(exc), message=message, operation="initialize")
                raise MT5DisconnectedError(message) from exc

            if not initialized:
                error = self._capture_error("initialize", "MetaTrader 5 returned no IPC connection.")
                self._reset_session()
                message = error.message
                if error.code in BROKER_CODES:
                    raise MT5BrokerDisconnectedError(message, self._details(error))
                if error.code in (-2, -3, -10003):
                    raise MT5TerminalNotFoundError(message, self._details(error))
                raise MT5DisconnectedError(message, self._details(error))

            self._ipc_connected = True
            info = _terminal_info_to_dict(module.terminal_info())
            if not info:
                error = self._capture_error("terminal_info", "IPC initialized, but terminal_info() returned nothing.")
                self._hard_shutdown()
                raise MT5DisconnectedError(
                    f"IPC initialized, but terminal_info() is unavailable. {error.message}",
                    self._details(error),
                )
            self._terminal_info = info
            if info.get("connected") is not True:
                error = self._capture_error("terminal_info", "The terminal is not connected to the broker server.")
                self._hard_shutdown()
                raise MT5BrokerDisconnectedError(
                    f"The terminal is running but not connected to its broker server. {error.message}",
                    self._details(error),
                )

            account = self._read_account_info()
            if not account:
                error = self._capture_error("account_info", "The terminal did not expose account information.")
                self._hard_shutdown()
                raise MT5AccountUnavailableError(
                    "The terminal is connected, but account information is unavailable. "
                    "Log in to a broker account in the terminal and retry.",
                    self._details(error),
                )

            self._account_info = account
            self._account_available = True
            self._broker_connected = True
            self._connected = True
            self._last_error = None
            if target:
                self._terminal_path = target
            logger.info(
                "MT5 session ready: %s | %s | build %s | account %s",
                info.get("name") or "terminal",
                info.get("company") or "unknown broker",
                info.get("build"),
                account.get("login_masked"),
            )
            return info

    def _read_account_info(self) -> dict[str, Any]:
        for attempt in range(ACCOUNT_INFO_RETRIES):
            try:
                info = self.module.account_info()
            except Exception:  # pragma: no cover - defensive
                info = None
            if info is not None:
                return _account_info_to_dict(info)
            if attempt < ACCOUNT_INFO_RETRIES - 1:
                time.sleep(ACCOUNT_INFO_RETRY_SECONDS)
        return {}

    def _hard_shutdown(self) -> None:
        try:
            if self._module is not None:
                self._module.shutdown()
        except Exception:  # pragma: no cover - best effort
            pass
        self._reset_session()

    def _reset_session(self) -> None:
        self._connected = False
        self._ipc_connected = False
        self._broker_connected = False
        self._account_available = False
        self._terminal_info = {}
        self._account_info = {}

    def shutdown(self) -> None:
        with self._lock:
            if self._module is not None:
                try:
                    self._module.shutdown()
                except Exception:  # pragma: no cover - best effort
                    pass
            self._reset_session()

    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    # ------------------------------------------------------------------ probes
    def terminal_info(self) -> dict[str, Any]:
        with self._lock:
            if self._module is None:
                return {}
            try:
                info = _terminal_info_to_dict(self._module.terminal_info())
            except Exception:  # pragma: no cover
                return {}
            if info:
                self._terminal_info = info
            return info

    def account_info(self) -> dict[str, Any]:
        with self._lock:
            if self._module is None:
                return {}
            try:
                info = _account_info_to_dict(self._module.account_info())
            except Exception:  # pragma: no cover
                return {}
            if info:
                self._account_info = info
            return info

    def health(self) -> dict[str, Any]:
        """Probe IPC, broker and account independently without reinitializing."""

        with self._lock:
            if self._module is None:
                return {
                    "terminal_connected": False,
                    "broker_connected": False,
                    "account_available": False,
                    "connected": False,
                    "terminal": {},
                    "account": {},
                    "error": self.last_error_detail,
                }
            info = self.terminal_info()
            if not info:
                error = self._read_last_error("health.terminal_info")
                self._mark_down(
                    "The MetaTrader 5 IPC connection is no longer available."
                    + (f" {error.message}" if error else ""),
                    code=error.code if error else None,
                    description=error.description if error else None,
                    operation="health",
                )
                return {
                    "terminal_connected": False,
                    "broker_connected": False,
                    "account_available": False,
                    "connected": False,
                    "terminal": {},
                    "account": {},
                    "error": self.last_error_detail,
                }

            self._ipc_connected = True
            self._terminal_info = info
            if info.get("connected") is not True:
                error = self._capture_error("health.broker", "The terminal is not connected to the broker server.")
                self._broker_connected = False
                self._connected = False
                self._account_available = False
                self._last_error = MT5Error(
                    code=error.code,
                    description=error.description,
                    message=f"The broker session is disconnected. {error.message}",
                    operation="health",
                )
                return {
                    "terminal_connected": True,
                    "broker_connected": False,
                    "account_available": False,
                    "connected": False,
                    "terminal": info,
                    "account": {},
                    "error": self.last_error_detail,
                }

            account = self.account_info()
            if not account:
                error = self._capture_error("health.account_info", "Account information is unavailable.")
                self._broker_connected = True
                self._account_available = False
                self._connected = False
                self._last_error = MT5Error(
                    code=error.code,
                    description=error.description,
                    message="The terminal is connected, but account information is unavailable.",
                    operation="health",
                )
                return {
                    "terminal_connected": True,
                    "broker_connected": True,
                    "account_available": False,
                    "connected": False,
                    "terminal": info,
                    "account": {},
                    "error": self.last_error_detail,
                }

            self._account_info = account
            self._broker_connected = True
            self._account_available = True
            self._connected = True
            self._last_error = None
            return {
                "terminal_connected": True,
                "broker_connected": True,
                "account_available": True,
                "connected": True,
                "terminal": info,
                "account": account,
                "error": None,
            }

    def _require(self) -> Any:
        if not self._connected:
            detail = self.last_error_detail or {}
            raise MT5DisconnectedError(
                self.last_error or "MetaTrader 5 is not connected.",
                detail,
            )
        return self.module

    # ---------------------------------------------------------------- symbols
    def symbols(self) -> list[dict[str, Any]]:
        with self._lock:
            module = self._require()
            try:
                raw = module.symbols_get()
            except Exception as exc:  # pragma: no cover - defensive
                error = self._capture_error("symbols_get", f"The terminal did not return a symbol list: {exc}")
                self._mark_down(error.message, code=error.code, description=error.description, operation="symbols_get")
                raise MT5DisconnectedError(error.message, self._details(error)) from exc
            if raw is None:
                error = self._capture_error("symbols_get", "The terminal did not return a symbol list.")
                if self._is_disconnect(error):
                    self._mark_down(error.message, code=error.code, description=error.description, operation="symbols_get")
                    raise MT5DisconnectedError(error.message, self._details(error))
                raise MT5DataError(error.message, self._details(error))
            return [_symbol_info_to_dict(item) for item in raw]

    def symbol(self, name: str) -> dict[str, Any] | None:
        with self._lock:
            module = self._require()
            try:
                info = module.symbol_info(name)
            except Exception:  # pragma: no cover
                return None
            return _symbol_info_to_dict(info) if info is not None else None

    def select_symbol(self, name: str) -> dict[str, Any]:
        """Select, verify symbol_info and verify a tick, or raise."""

        with self._lock:
            module = self._require()
            try:
                info = module.symbol_info(name)
            except Exception as exc:  # pragma: no cover
                raise MT5SymbolUnavailableError(f"symbol_info('{name}') failed: {exc}") from exc
            if info is None:
                error = self._capture_error("symbol_info", f"Symbol '{name}' was not found on this broker server.")
                raise MT5SymbolUnavailableError(error.message, self._details(error))

            if not bool(_safe_getattr(info, "visible", False)):
                try:
                    selected = bool(module.symbol_select(name, True))
                except Exception as exc:  # pragma: no cover
                    raise MT5SymbolUnavailableError(f"symbol_select('{name}') failed: {exc}") from exc
                if not selected:
                    error = self._capture_error("symbol_select", f"The terminal refused to select '{name}'.")
                    raise MT5SymbolUnavailableError(error.message, self._details(error))
                info = module.symbol_info(name)
                if info is None:
                    error = self._capture_error("symbol_info", f"Symbol '{name}' disappeared after selection.")
                    raise MT5SymbolUnavailableError(error.message, self._details(error))

            tick = module.symbol_info_tick(name)
            if tick is None:
                error = self._capture_error("symbol_info_tick", f"Symbol '{name}' is selected but no tick is available.")
                raise MT5SymbolUnavailableError(
                    f"Symbol '{name}' was selected, but the broker returned no tick. {error.message}",
                    self._details(error),
                )
            return {"symbol": _symbol_info_to_dict(info), "tick": _tick_to_dict(tick)}

    def ensure_symbol_visible(self, name: str) -> bool:
        with self._lock:
            module = self._require()
            info = module.symbol_info(name)
            if info is None:
                return False
            if bool(_safe_getattr(info, "visible", False)):
                return True
            return bool(module.symbol_select(name, True))

    # ----------------------------------------------------------------- market
    def tick(self, name: str) -> dict[str, Any]:
        with self._lock:
            module = self._require()
            try:
                tick = module.symbol_info_tick(name)
            except Exception as exc:  # pragma: no cover
                error = self._capture_error("symbol_info_tick", f"Tick request failed: {exc}")
                if self._is_disconnect(error):
                    self._mark_down(error.message, code=error.code, description=error.description, operation="tick")
                    raise MT5DisconnectedError(error.message, self._details(error)) from exc
                raise MT5TickUnavailableError(error.message, self._details(error)) from exc
            if tick is None:
                error = self._capture_error("symbol_info_tick", f"No tick is available for {name}.")
                if self._is_disconnect(error):
                    self._mark_down(error.message, code=error.code, description=error.description, operation="tick")
                    raise MT5DisconnectedError(error.message, self._details(error))
                raise MT5TickUnavailableError(error.message, self._details(error))
            return _tick_to_dict(tick)

    def timeframe_constant(self, timeframe: Timeframe) -> Any:
        name = TIMEFRAME_MT5_CONSTANT[timeframe]
        module = self.module
        try:
            return getattr(module, name)
        except AttributeError as exc:  # pragma: no cover - version mismatch
            raise MT5DataError(f"MetaTrader 5 does not expose {name}.") from exc

    def rates(self, name: str, timeframe: Timeframe, count: int) -> list[dict[str, Any]]:
        with self._lock:
            module = self._require()
            constant = self.timeframe_constant(timeframe)
            try:
                records = module.copy_rates_from_pos(name, constant, 0, max(1, int(count)))
            except Exception as exc:  # pragma: no cover
                error = self._capture_error("copy_rates_from_pos", f"Candle request failed: {exc}")
                if self._is_disconnect(error):
                    self._mark_down(error.message, code=error.code, description=error.description, operation="rates")
                    raise MT5DisconnectedError(error.message, self._details(error)) from exc
                raise MT5HistoryUnavailableError(error.message, self._details(error)) from exc
            if records is None:
                error = self._capture_error(
                    "copy_rates_from_pos",
                    f"No candle history returned for {name} {timeframe.value}.",
                )
                if self._is_disconnect(error):
                    self._mark_down(error.message, code=error.code, description=error.description, operation="rates")
                    raise MT5DisconnectedError(error.message, self._details(error))
                raise MT5HistoryUnavailableError(error.message, self._details(error))
            return _records_to_rows(records)

    def rates_range(self, name: str, timeframe: Timeframe, start_epoch: int, count: int) -> list[dict[str, Any]]:
        with self._lock:
            module = self._require()
            constant = self.timeframe_constant(timeframe)
            try:
                start = datetime.fromtimestamp(start_epoch, tz=UTC)
                records = module.copy_rates_from(name, constant, start, max(1, int(count)))
            except Exception as exc:  # pragma: no cover - fallback path
                logger.debug("copy_rates_from failed, falling back to positional copy: %s", exc)
                try:
                    records = module.copy_rates_from_pos(name, constant, 0, max(1, int(count)))
                except Exception as inner:  # pragma: no cover
                    error = self._capture_error("copy_rates_from", f"Candle request failed: {inner}")
                    raise MT5HistoryUnavailableError(error.message, self._details(error)) from inner
            if records is None:
                error = self._capture_error("copy_rates_from", f"No candle history returned for {name}.")
                raise MT5HistoryUnavailableError(error.message, self._details(error))
            return _records_to_rows(records)

    def daily_reference(self, name: str) -> dict[str, Any] | None:
        """Yesterday's close/last daily bar for a percentage change reference."""

        with self._lock:
            module = self._require()
            try:
                constant = module.TIMEFRAME_D1
                records = module.copy_rates_from_pos(name, constant, 0, 2)
            except Exception:
                return None
            rows = _records_to_rows(records)
            if not rows:
                return None
            return rows[-1]

    def symbol_names(self, names: Iterable[str]) -> list[dict[str, Any]]:
        discovered = []
        for name in names:
            info = self.symbol(name)
            if info:
                discovered.append(info)
        return discovered
