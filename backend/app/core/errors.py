"""Stable, user-readable API errors."""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """An error that maps directly onto a documented API error response."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class MT5NotInstalledError(ApiError):
    def __init__(self, message: str = "The MetaTrader5 Python package is not installed.", details=None):
        super().__init__("MT5_PACKAGE_MISSING", message, 503, details)


class MT5DisconnectedError(ApiError):
    def __init__(
        self,
        message: str = "MetaTrader 5 terminal is not reachable.",
        details=None,
        code: str = "MT5_NOT_CONNECTED",
    ):
        super().__init__(code, message, 503, details)


class MT5TerminalNotFoundError(MT5DisconnectedError):
    def __init__(self, message: str = "MetaTrader 5 terminal executable was not found.", details=None):
        super().__init__(message, details, code="MT5_TERMINAL_NOT_FOUND")


class MT5BrokerDisconnectedError(MT5DisconnectedError):
    def __init__(self, message: str = "The terminal is not connected to the broker server.", details=None):
        super().__init__(message, details, code="MT5_BROKER_DISCONNECTED")


class MT5AccountUnavailableError(MT5DisconnectedError):
    def __init__(self, message: str = "The terminal did not expose account information.", details=None):
        super().__init__(message, details, code="MT5_ACCOUNT_UNAVAILABLE")


class MT5DataError(ApiError):
    def __init__(self, message: str, details=None, code: str = "MT5_DATA_UNAVAILABLE"):
        super().__init__(code, message, 422, details)


class MT5SymbolUnavailableError(MT5DataError):
    def __init__(self, message: str, details=None):
        super().__init__(message, details, code="MT5_SYMBOL_UNAVAILABLE")


class MT5TickUnavailableError(MT5DataError):
    def __init__(self, message: str = "No tick is available for the selected symbol.", details=None):
        super().__init__(message, details, code="MT5_TICK_UNAVAILABLE")


class MT5HistoryUnavailableError(MT5DataError):
    def __init__(self, message: str = "No candle history is available for the selected symbol.", details=None):
        super().__init__(message, details, code="MT5_HISTORY_UNAVAILABLE")


class MarketDataUnavailableError(ApiError):
    def __init__(
        self,
        message: str = "The selected market data provider is unavailable.",
        details=None,
        code: str = "MARKET_DATA_UNAVAILABLE",
    ):
        super().__init__(code, message, 503, details)


class ProviderSelectionError(ApiError):
    def __init__(self, message: str, details=None):
        super().__init__("PROVIDER_SELECTION_ERROR", message, 422, details)


class UnsupportedScopeError(ApiError):
    """A market-intelligence request outside the approved symbol/timeframe scope."""

    def __init__(self, message: str, details=None):
        super().__init__("UNSUPPORTED_SCOPE", message, 422, details)


class AnalysisUnavailableError(ApiError):
    """The deterministic analysis service is not available in this process."""

    def __init__(
        self,
        message: str = "Deterministic market analysis is not available.",
        details=None,
    ):
        super().__init__("MARKET_ANALYSIS_UNAVAILABLE", message, 503, details)


class StrategyUnavailableError(ApiError):
    """The deterministic strategy service is not available in this process."""

    def __init__(
        self,
        message: str = "Deterministic strategy evaluation is not available.",
        details=None,
    ) -> None:
        super().__init__("STRATEGY_UNAVAILABLE", message, 503, details)


class ForecastUnavailableError(ApiError):
    def __init__(
        self,
        message: str = "The PATRON forecast model is not available. Check /api/v1/patron/readiness.",
        details=None,
    ):
        super().__init__("PATRON_UNAVAILABLE", message, 503, details)


class ValidationError(ApiError):
    def __init__(self, message: str, details=None):
        super().__init__("VALIDATION_ERROR", message, 422, details)


class NotFoundError(ApiError):
    def __init__(self, message: str = "Resource not found.", details=None):
        super().__init__("NOT_FOUND", message, 404, details)
