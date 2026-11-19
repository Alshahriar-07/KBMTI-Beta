"""Explicit MetaTrader 5 connection states.

A single boolean cannot describe the difference between a missing Python
package, a terminal that is installed but closed, a terminal whose IPC bridge is
up while the broker session is down, and a fully streaming symbol. The service
exposes this state plus independent capability flags.
"""

from __future__ import annotations

from enum import StrEnum


class ConnectionState(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    TERMINAL_NOT_FOUND = "TERMINAL_NOT_FOUND"
    INITIALIZING = "INITIALIZING"
    TERMINAL_CONNECTED = "TERMINAL_CONNECTED"
    BROKER_DISCONNECTED = "BROKER_DISCONNECTED"
    SYMBOL_NOT_SELECTED = "SYMBOL_NOT_SELECTED"
    WAITING_FOR_MARKET_DATA = "WAITING_FOR_MARKET_DATA"
    MARKET_DATA_READY = "MARKET_DATA_READY"
    RECONNECTING = "RECONNECTING"
    ERROR = "ERROR"


STATE_LABELS: dict[ConnectionState, str] = {
    ConnectionState.NOT_CONFIGURED: "Terminal not selected",
    ConnectionState.TERMINAL_NOT_FOUND: "Terminal not found",
    ConnectionState.INITIALIZING: "Initializing",
    ConnectionState.TERMINAL_CONNECTED: "Terminal connected",
    ConnectionState.BROKER_DISCONNECTED: "Broker disconnected",
    ConnectionState.SYMBOL_NOT_SELECTED: "Symbol not selected",
    ConnectionState.WAITING_FOR_MARKET_DATA: "Waiting for market data",
    ConnectionState.MARKET_DATA_READY: "Market data ready",
    ConnectionState.RECONNECTING: "Reconnecting",
    ConnectionState.ERROR: "Error",
}

# States in which the terminal and broker session are believed to be up.
SESSION_STATES = {
    ConnectionState.TERMINAL_CONNECTED,
    ConnectionState.SYMBOL_NOT_SELECTED,
    ConnectionState.WAITING_FOR_MARKET_DATA,
    ConnectionState.MARKET_DATA_READY,
}
