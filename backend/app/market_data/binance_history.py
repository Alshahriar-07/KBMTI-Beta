"""Paginated Binance Spot historical klines client.

The live provider (``app.market_data.providers.binance``) owns the UI stream and a
bounded rolling window. This client exists for the two callers that need arbitrary
history and full-precision base-asset volume:

* the PATRON forecasting pipeline (96 closed candles + 384 warm-up bars), and
* the dataset builder that trains a PATRON checkpoint.

It uses Binance's public data endpoint only. No API key, signature or account
access is involved. Requests are sequential, rate-limit aware and retried with
exponential backoff; responses are validated before they are returned.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import MarketDataUnavailableError, ValidationError

logger = logging.getLogger(__name__)

INTERVAL_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "8h": 28800,
    "12h": 43200,
    "1d": 86400,
}

MAX_PAGE_LIMIT = 1000
MAX_PAGES = 400
RATE_LIMIT_HEADROOM = 5200  # Binance IP limit is 6000 weight/minute for /api/v3/klines
RECENT_CACHE_SECONDS = 5.0
MAX_VALIDATION_WARNINGS = 5


@dataclass(frozen=True, slots=True)
class BinanceKline:
    """One validated, closed Binance kline with float base-asset volume."""

    open_time_ms: int
    close_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    trades: int

    @property
    def open_time(self) -> int:
        return self.open_time_ms // 1000

    @property
    def close_time(self) -> int:
        return self.close_time_ms // 1000

    @property
    def timestamp_open(self) -> str:
        return datetime.fromtimestamp(self.open_time_ms / 1000, tz=UTC).isoformat()

    @property
    def timestamp_close(self) -> str:
        return datetime.fromtimestamp(self.close_time_ms / 1000, tz=UTC).isoformat()

    def to_row(self) -> dict[str, Any]:
        return {
            "open_time_ms": self.open_time_ms,
            "close_time_ms": self.close_time_ms,
            "timestamp_open": self.timestamp_open,
            "timestamp_close": self.timestamp_close,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "trades": self.trades,
        }


def _now_ms() -> int:
    return int(time.time() * 1000)


def parse_klines(payload: Any) -> tuple[list[BinanceKline], list[str]]:
    """Validate Binance kline arrays and drop structurally invalid bars."""

    if not isinstance(payload, list):
        raise MarketDataUnavailableError(
            "Binance returned an unexpected klines payload.",
            {"payload_type": type(payload).__name__},
            code="BINANCE_KLINES_INVALID",
        )

    warnings: list[str] = []
    seen: dict[int, BinanceKline] = {}
    invalid = 0
    duplicates = 0
    for row in payload:
        if not isinstance(row, (list, tuple)) or len(row) < 7:
            invalid += 1
            continue
        try:
            kline = BinanceKline(
                open_time_ms=int(row[0]),
                close_time_ms=int(row[6]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
                trades=int(row[8]) if len(row) > 8 and row[8] is not None else 0,
            )
        except (TypeError, ValueError):
            invalid += 1
            continue
        prices = (kline.open, kline.high, kline.low, kline.close)
        if kline.open_time_ms <= 0 or any(value <= 0 for value in prices):
            invalid += 1
            continue
        if kline.high < max(kline.open, kline.close, kline.low):
            invalid += 1
            continue
        if kline.low > min(kline.open, kline.close, kline.high):
            invalid += 1
            continue
        if kline.volume < 0:
            invalid += 1
            continue
        if kline.open_time_ms in seen:
            duplicates += 1
        seen[kline.open_time_ms] = kline

    if invalid:
        warnings.append(f"{invalid} Binance kline(s) failed integrity checks and were excluded.")
    if duplicates:
        warnings.append(f"{duplicates} duplicate Binance kline timestamp(s) were collapsed.")
    return [seen[key] for key in sorted(seen)], warnings


class BinanceHistoryClient:
    """Read-only Binance REST client for contiguous historical candles."""

    def __init__(self, settings: Settings, http_client: Any | None = None) -> None:
        self.settings = settings
        self._http = http_client or httpx.Client(
            timeout=httpx.Timeout(settings.binance_timeout_seconds, connect=5.0),
            follow_redirects=True,
            headers={"User-Agent": "KBMTI/1.1 (+local research client)"},
        )
        self._base = settings.binance_rest_url.rstrip("/")
        self._lock = threading.RLock()
        self._recent_cache: dict[tuple[str, str], tuple[float, list[BinanceKline]]] = {}
        self._used_weight = 0
        self._weight_reset_at = 0.0
        self._last_request_at: str | None = None
        self._request_count = 0
        self._retry_count = 0
        self._last_error: str | None = None

    # ------------------------------------------------------------------ HTTP
    def _throttle(self) -> None:
        """Keep this process well below Binance's IP weight limit."""

        with self._lock:
            now = time.monotonic()
            if self._weight_reset_at and now >= self._weight_reset_at:
                self._used_weight = 0
                self._weight_reset_at = 0.0
            if self._used_weight < RATE_LIMIT_HEADROOM or not self._weight_reset_at:
                return
            wait = max(0.0, self._weight_reset_at - now)
        if wait:
            logger.info("Binance weight headroom reached; pausing %.1fs", wait)
            time.sleep(min(wait, 61.0))

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        url = f"{self._base}{path}"
        attempts = 4
        last_error: Exception | None = None
        for attempt in range(attempts):
            self._throttle()
            try:
                response = self._http.get(url, params=params)
                if response.status_code == 429:
                    retry_after = _retry_after_seconds(response)
                    self._retry_count += 1
                    logger.warning("Binance rate limit hit; retrying in %.1fs", retry_after)
                    time.sleep(retry_after)
                    continue
                if response.status_code == 418:
                    raise MarketDataUnavailableError(
                        "Binance temporarily blocked this IP after repeated rate-limit violations.",
                        {"status": 418},
                        code="BINANCE_IP_BLOCKED",
                    )
                response.raise_for_status()
                with self._lock:
                    self._used_weight = _used_weight(response) or self._used_weight
                    if self._used_weight >= 100:
                        # Weight is reported per rolling minute; reset conservatively.
                        self._weight_reset_at = time.monotonic() + 60.0
                    self._last_request_at = datetime.now(UTC).isoformat(timespec="seconds")
                    self._request_count += 1
                    self._last_error = None
                return response.json()
            except MarketDataUnavailableError:
                raise
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(0.5 * (2**attempt))
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                last_error = exc
                if status in {400, 404}:
                    raise MarketDataUnavailableError(
                        f"Binance rejected the kline request (HTTP {status}).",
                        {"url": url, "params": params},
                        code="BINANCE_KLINES_REJECTED",
                    ) from exc
                if attempt + 1 < attempts:
                    time.sleep(0.5 * (2**attempt))
            except Exception as exc:  # noqa: BLE001 - normalized below
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(0.5 * (2**attempt))

        with self._lock:
            self._last_error = str(last_error)
        raise MarketDataUnavailableError(
            "Binance historical klines are unavailable after retries.",
            {"url": url, "error": str(last_error)},
            code="BINANCE_HISTORY_UNAVAILABLE",
        ) from last_error

    # ----------------------------------------------------------------- query
    def _fetch_page(
        self,
        symbol: str,
        interval: str,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = MAX_PAGE_LIMIT,
    ) -> tuple[list[BinanceKline], list[str]]:
        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": max(1, min(int(limit), MAX_PAGE_LIMIT)),
        }
        if start_ms is not None:
            params["startTime"] = int(start_ms)
        if end_ms is not None:
            params["endTime"] = int(end_ms)
        payload = self._get("/api/v3/klines", params)
        return parse_klines(payload)

    def recent(
        self,
        symbol: str,
        interval: str,
        limit: int = 520,
        *,
        force: bool = False,
    ) -> list[BinanceKline]:
        """Return the most recent *closed* klines, oldest -> newest."""

        normalized = interval.lower()
        if normalized not in INTERVAL_SECONDS:
            raise ValidationError(f"Unsupported Binance interval '{interval}'.")
        wanted = max(1, int(limit))
        # One 1000-bar page serves every inference/evaluation window. Cache the
        # page, not each requested slice, so a close event causes one REST call
        # instead of three separate calls for 480, 520 and 1000 rows.
        key = (symbol.upper(), normalized)
        rows: list[BinanceKline] | None = None
        if wanted <= MAX_PAGE_LIMIT:
            with self._lock:
                cached = self._recent_cache.get(key)
                if cached and not force and time.monotonic() - cached[0] < RECENT_CACHE_SECONDS:
                    rows = list(cached[1])

        if rows is None:
            rows = self._closed_klines(symbol, normalized, limit=max(wanted, MAX_PAGE_LIMIT))
            if wanted <= MAX_PAGE_LIMIT:
                with self._lock:
                    self._recent_cache[key] = (time.monotonic(), list(rows))

        if len(rows) < wanted:
            # Ask for a wider page once; new listings legitimately have fewer bars.
            logger.info(
                "Binance returned %d of %d requested %s %s candles.",
                len(rows),
                wanted,
                symbol.upper(),
                normalized,
            )
        return rows[-wanted:]

    def _closed_klines(self, symbol: str, interval: str, limit: int) -> list[BinanceKline]:
        wanted = max(1, int(limit))
        # One page covers every realistic inference window (96 + 384 bars).
        if wanted <= MAX_PAGE_LIMIT:
            page, _ = self._fetch_page(symbol, interval, limit=MAX_PAGE_LIMIT)
            closed = [row for row in page if row.close_time_ms <= _now_ms() - 1000]
            return closed[-wanted:]

        seconds = INTERVAL_SECONDS[interval]
        end_ms = _now_ms()
        start_ms = end_ms - seconds * 1000 * (wanted + 5)
        rows = self.range(symbol, interval, start_ms, end_ms)
        return rows[-wanted:]

    def range(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int | None = None,
    ) -> list[BinanceKline]:
        """Fetch a contiguous time range with pagination. Oldest -> newest."""

        normalized = interval.lower()
        if normalized not in INTERVAL_SECONDS:
            raise ValidationError(f"Unsupported Binance interval '{interval}'.")
        if start_ms <= 0:
            raise ValidationError("start_ms must be a positive epoch millisecond value.")
        step_ms = INTERVAL_SECONDS[normalized] * 1000
        cursor = int(start_ms)
        end = int(end_ms) if end_ms is not None else _now_ms()
        if end <= cursor:
            return []

        rows: dict[int, BinanceKline] = {}
        pages = 0
        while cursor < end and pages < MAX_PAGES:
            page, _warnings = self._fetch_page(
                symbol, normalized, start_ms=cursor, end_ms=end, limit=MAX_PAGE_LIMIT
            )
            if not page:
                break
            for kline in page:
                if kline.open_time_ms >= end:
                    continue
                if kline.close_time_ms > _now_ms() - 1000:
                    continue
                rows[kline.open_time_ms] = kline
            last_open = page[-1].open_time_ms
            next_cursor = last_open + step_ms
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            pages += 1
            if len(page) < MAX_PAGE_LIMIT:
                break

        ordered = [rows[key] for key in sorted(rows)]
        if not ordered:
            return []
        gaps = [
            (ordered[index - 1].open_time_ms, ordered[index].open_time_ms)
            for index in range(1, len(ordered))
            if ordered[index].open_time_ms - ordered[index - 1].open_time_ms != step_ms
        ]
        if gaps:
            logger.warning(
                "Binance %s %s history contains %d gap(s); first at %s",
                symbol.upper(),
                normalized,
                len(gaps),
                gaps[0],
            )
        return ordered

    # ------------------------------------------------------------ diagnostics
    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "client": "binance-history",
                "rest_base": self._base,
                "requests": self._request_count,
                "retries": self._retry_count,
                "used_weight": self._used_weight,
                "last_request_at": self._last_request_at,
                "last_error": self._last_error,
                "cached_windows": len(self._recent_cache),
            }


def _used_weight(response: Any) -> int:
    headers = getattr(response, "headers", {}) or {}
    for key in ("x-mbx-used-weight-1m", "X-MBX-USED-WEIGHT-1M"):
        try:
            value = headers.get(key)
        except AttributeError:  # pragma: no cover - dict-like test doubles
            value = None
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0
    return 0


def _retry_after_seconds(response: Any) -> float:
    headers = getattr(response, "headers", {}) or {}
    value = headers.get("Retry-After") or headers.get("retry-after")
    try:
        return max(1.0, min(60.0, float(value)))
    except (TypeError, ValueError):
        return 5.0
