"""A deterministic stand-in for the MetaTrader5 module used by unit and API tests.

Each layer can fail independently so the connection state machine is exercised
without a real terminal: IPC, terminal info, broker session, account info, symbol
selection, live ticks and historical bars.
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400}
TF_CONSTANTS = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 16385, "H4": 16388}
BASE_TIME = 1_700_000_000


def make_candles(
    count: int = 220,
    timeframe: str = "M15",
    *,
    base: float = 64_000.0,
    drift: float = 14.0,
    amplitude: float = 45.0,
) -> list[dict[str, Any]]:
    step = TF_SECONDS[timeframe]
    end = (BASE_TIME // step) * step
    rows: list[dict[str, Any]] = []
    for index in range(count):
        timestamp = end - (count - 1 - index) * step
        wave = amplitude * math.sin(index / 7.0)
        open_price = base + drift * index + wave
        close_price = open_price + drift * 0.55 + amplitude * 0.35 * math.sin(index / 3.0)
        high = max(open_price, close_price) + 32.0 + (index % 5)
        low = min(open_price, close_price) - 30.0 - (index % 4)
        rows.append(
            {
                "time": timestamp,
                "open": round(open_price, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close_price, 2),
                "tick_volume": 120 + (index * 7) % 90,
                "spread": 25,
                "real_volume": 0,
            }
        )
    return rows


class FakeMT5:
    __version__ = "5.0.0-fake"

    TIMEFRAME_M1 = TF_CONSTANTS["M1"]
    TIMEFRAME_M5 = TF_CONSTANTS["M5"]
    TIMEFRAME_M15 = TF_CONSTANTS["M15"]
    TIMEFRAME_M30 = TF_CONSTANTS["M30"]
    TIMEFRAME_H1 = TF_CONSTANTS["H1"]
    TIMEFRAME_H4 = TF_CONSTANTS["H4"]
    TIMEFRAME_D1 = 16408

    def __init__(
        self,
        *,
        symbol: str = "BTCUSDm",
        connected: bool = True,
        candles: list[dict[str, Any]] | None = None,
        fail_initialize: bool = False,
        ipc_available: bool = True,
        terminal_info_none: bool = False,
        account_available: bool = True,
        tick_available: bool = True,
        history_available: bool = True,
        history_limit: int | None = None,
        symbol_select_ok: bool = True,
        symbols: list[str] | None = None,
    ) -> None:
        self.symbol = symbol
        self.broker_connected = connected
        self.fail_initialize = fail_initialize
        self.ipc_available = ipc_available
        self.terminal_info_none = terminal_info_none
        self.account_available = account_available
        self.tick_available = tick_available
        self.history_available = history_available
        self.history_limit = history_limit
        self.symbol_select_ok = symbol_select_ok
        self.symbols = symbols or ["BTCUSDm", "BTCUSD", "BTCUSD.", "ETHUSD", "XAUUSD"]
        self.candles = candles if candles is not None else make_candles()
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.initialize_kwargs: list[dict[str, Any]] = []
        self.initialized = False
        self._tick_time = self.candles[-1]["time"] if self.candles else BASE_TIME
        self._tick_override: int | None = None
        self._account = SimpleNamespace(
            login=12345678,
            server="Test-Server",
            company="Test Broker Ltd",
            currency="USD",
            leverage=100,
            trade_mode=0,
            trade_allowed=True,
        )

    @property
    def connected(self) -> bool:
        return self.broker_connected

    @connected.setter
    def connected(self, value: bool) -> None:
        self.broker_connected = value

    # --- lifecycle -----------------------------------------------------------
    def initialize(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(("initialize", args))
        self.initialize_kwargs.append(dict(kwargs))
        if self.fail_initialize or not self.ipc_available:
            return False
        self.initialized = True
        return True

    def shutdown(self) -> None:
        self.calls.append(("shutdown", ()))
        self.initialized = False

    def last_error(self):  # type: ignore[no-untyped-def]
        if self.fail_initialize:
            return (-10003, "Terminal process not running")
        if not self.ipc_available:
            return (-10004, "No IPC connection")
        if not self.initialized:
            return (-10007, "Terminal is not initialized")
        if not self.broker_connected:
            return (-10009, "Not connected to trade server")
        if not self.account_available:
            return (-6, "Authorization failed")
        return (0, "ok")

    def terminal_info(self):  # type: ignore[no-untyped-def]
        if not self.initialized or not self.ipc_available or self.terminal_info_none:
            return None
        return SimpleNamespace(
            name="MetaTrader 5",
            company="Test Broker Ltd",
            path="C:/Program Files/MetaTrader 5/terminal64.exe",
            data_path="C:/Users/Test/AppData/Roaming/MetaQuotes/Terminal/ABC",
            common_data_path="C:/Users/Test/AppData/Roaming/MetaQuotes/Terminal/Common",
            build=4520,
            language=0,
            maxbars=100000,
            connected=self.broker_connected,
            trade_allowed=True,
            dlls_allowed=False,
            community_connected=False,
            ping_last=12,
        )

    def account_info(self):  # type: ignore[no-untyped-def]
        if not self.initialized or not self.account_available:
            return None
        return self._account

    # --- symbols -------------------------------------------------------------
    def _symbol_info(self, name: str) -> SimpleNamespace | None:
        meta = {
            "BTCUSDm": ("Bitcoin vs US Dollar", "Crypto\\BTCUSDm", "BTC", "USD"),
            "BTCUSD": ("Bitcoin / US Dollar", "Crypto\\BTCUSD", "BTC", "USD"),
            "BTCUSD.": ("Bitcoin vs Dollar", "Crypto\\BTCUSD.", "BTC", "USD"),
            "ETHUSD": ("Ethereum vs US Dollar", "Crypto\\ETHUSD", "ETH", "USD"),
            "XAUUSD": ("Gold vs US Dollar", "Metals\\XAUUSD", "XAU", "USD"),
        }
        if name not in meta:
            return None
        description, path, base, quote = meta[name]
        bid, ask = self._prices()
        return SimpleNamespace(
            name=name,
            description=description,
            path=path,
            digits=2,
            point=0.01,
            spread=25,
            trade_mode=4,
            currency_base=base,
            currency_profit=quote,
            visible=True,
            volume_min=0.01,
            volume_step=0.01,
            bid=bid,
            ask=ask,
        )

    def symbols_get(self):  # type: ignore[no-untyped-def]
        if not self.initialized or not self.ipc_available:
            return None
        return [self._symbol_info(name) for name in self.symbols if self._symbol_info(name)]

    def symbol_info(self, name: str):  # type: ignore[no-untyped-def]
        if not self.initialized:
            return None
        return self._symbol_info(name)

    def symbol_select(self, name: str, visible: bool = True):  # type: ignore[no-untyped-def]
        if not self.initialized:
            return False
        return self.symbol_select_ok and self._symbol_info(name) is not None

    def _prices(self) -> tuple[float, float]:
        last_close = float(self.candles[-1]["close"]) if self.candles else 64_000.0
        return round(last_close - 0.13, 2), round(last_close + 0.12, 2)

    def symbol_info_tick(self, name: str):  # type: ignore[no-untyped-def]
        if not self.initialized or not self.tick_available or not self.candles:
            return None
        bid, ask = self._prices()
        last_close = float(self.candles[-1]["close"])
        return SimpleNamespace(
            time=self._tick_override or self._tick_time,
            time_msc=(self._tick_override or self._tick_time) * 1000,
            bid=bid,
            ask=ask,
            last=last_close,
            volume=17,
            flags=6,
        )

    def copy_rates_from_pos(self, name: str, timeframe: int, start: int, count: int):  # type: ignore[no-untyped-def]
        if not self.initialized or not self.history_available:
            return None
        limit = self.history_limit if self.history_limit is not None else count
        return self.candles[-limit:]

    def copy_rates_from(self, name: str, timeframe: int, start, count: int):  # type: ignore[no-untyped-def]
        return self.copy_rates_from_pos(name, timeframe, 0, count)

    # --- test helpers --------------------------------------------------------
    def set_tick_time(self, timestamp: int) -> None:
        self._tick_override = timestamp

    def close_terminal(self) -> None:
        """Simulate the user closing the terminal while the backend is polling."""

        self.ipc_available = False
        self.initialized = False

    def reopen_terminal(self) -> None:
        self.ipc_available = True
        self.fail_initialize = False
        self.initialized = False

    def set_broker_connected(self, value: bool) -> None:
        self.broker_connected = value

    def set_tick_available(self, value: bool) -> None:
        self.tick_available = value

    def set_history_available(self, value: bool) -> None:
        self.history_available = value
