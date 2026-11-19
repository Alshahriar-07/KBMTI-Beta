"""Application configuration for the KBMTI local backend.

All values are resolved once per process from environment variables so that
development, tests and the packaged desktop app can share one codebase.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

APP_NAME = "KBMTI"
APP_SLUG = "kbmti"
APP_VERSION = "1.2.0"
STAGE = 2
STAGE_LABEL = "Stage 2 - PATRON model intelligence"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8756

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PATRON_CHECKPOINT = PROJECT_ROOT / "backend" / "models" / "patron" / "best.pt"
DEFAULT_PATRON_WARMUP = PROJECT_ROOT / "backend" / "data" / "patron" / "BTCUSDT_15m.parquet"
DEFAULT_PATRON_CONFIG = PROJECT_ROOT / "PATRON" / "configs" / "model_config.yaml"

DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "tauri://localhost",
)


def _load_dotenv() -> None:
    """Load .env from the repository or backend folder without overriding real env vars."""

    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - optional in minimal installs
        return
    for candidate in (PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env"):
        if candidate.is_file():
            load_dotenv(candidate, override=False)


_load_dotenv()

def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    if not value or not value.strip():
        return default
    path = Path(value).expanduser()
    # Relative paths in .env are repository-relative, independent of the CWD
    # (the backend is normally started from backend/).
    return path if path.is_absolute() else PROJECT_ROOT / path


def _env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.environ.get(name)
    if not value or not value.strip():
        return default
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env_str(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env_str(name, str(default)))
    except ValueError:
        return default


def default_data_dir() -> Path:
    override = os.environ.get("KBMTI_DATA_DIR")
    if override:
        return Path(override).expanduser()
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "KBMTI"
    return Path.home() / ".kbmti"


@dataclass(frozen=True)
class Settings:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    data_dir: Path = None  # type: ignore[assignment]
    db_path: Path = None  # type: ignore[assignment]
    log_dir: Path = None  # type: ignore[assignment]
    poll_interval_seconds: float = 1.0
    candle_refresh_seconds: float = 5.0
    stale_after_seconds: float = 120.0
    default_timeframe: str = "M15"
    default_candle_limit: int = 500
    default_provider: str = "binance"
    binance_rest_url: str = "https://data-api.binance.vision"
    binance_ws_url: str = "wss://stream.binance.com:9443"
    binance_symbol: str = "BTCUSDT"
    binance_timeout_seconds: float = 12.0
    symbol_cache_seconds: float = 300.0
    signal_cache_seconds: float = 15.0
    heartbeat_seconds: float = 5.0
    mt5_connect_timeout_ms: int = 15_000
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    max_request_bytes: int = 1_048_576
    patron_enabled: bool = True
    patron_autoload: bool = True
    patron_checkpoint: Path = DEFAULT_PATRON_CHECKPOINT
    patron_warmup_path: Path = DEFAULT_PATRON_WARMUP
    patron_config_path: Path = DEFAULT_PATRON_CONFIG
    patron_threads: int = 4
    patron_history_bars: int = 520
    forecast_auto_enabled: bool = True
    forecast_poll_seconds: float = 5.0
    forecast_history_bars: int = 520

    def __post_init__(self) -> None:
        data_dir = Path(self.data_dir) if self.data_dir else default_data_dir()
        object.__setattr__(self, "data_dir", data_dir)
        object.__setattr__(self, "db_path", Path(self.db_path) if self.db_path else data_dir / "kbmti.db")
        object.__setattr__(self, "log_dir", Path(self.log_dir) if self.log_dir else data_dir / "logs")
        object.__setattr__(self, "patron_checkpoint", Path(self.patron_checkpoint))
        object.__setattr__(self, "patron_warmup_path", Path(self.patron_warmup_path))
        object.__setattr__(self, "patron_config_path", Path(self.patron_config_path))

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        host=_env_str("KBMTI_HOST", DEFAULT_HOST),
        port=_env_int("KBMTI_PORT", DEFAULT_PORT),
        poll_interval_seconds=_env_float("KBMTI_POLL_INTERVAL", 1.0),
        candle_refresh_seconds=_env_float("KBMTI_CANDLE_REFRESH", 5.0),
        stale_after_seconds=_env_float("KBMTI_STALE_SECONDS", 120.0),
        default_timeframe=_env_str("KBMTI_DEFAULT_TIMEFRAME", "M15").upper(),
        default_candle_limit=_env_int("KBMTI_DEFAULT_CANDLE_LIMIT", 500),
        default_provider=_env_str("KBMTI_DEFAULT_PROVIDER", "binance").lower(),
        binance_rest_url=_env_str("KBMTI_BINANCE_REST_URL", "https://data-api.binance.vision").rstrip("/"),
        binance_ws_url=_env_str("KBMTI_BINANCE_WS_URL", "wss://stream.binance.com:9443").rstrip("/"),
        binance_symbol=_env_str("KBMTI_BINANCE_SYMBOL", "BTCUSDT").upper(),
        binance_timeout_seconds=_env_float("KBMTI_BINANCE_TIMEOUT", 12.0),
        mt5_connect_timeout_ms=_env_int("KBMTI_MT5_TIMEOUT_MS", 15_000),
        cors_origins=_env_csv("KBMTI_CORS_ORIGINS", DEFAULT_CORS_ORIGINS),
        max_request_bytes=_env_int("KBMTI_MAX_REQUEST_BYTES", 1_048_576),
        patron_enabled=_env_bool("KBMTI_PATRON_ENABLED", True),
        patron_autoload=_env_bool("KBMTI_PATRON_AUTOLOAD", True),
        patron_checkpoint=_env_path("KBMTI_PATRON_CHECKPOINT", DEFAULT_PATRON_CHECKPOINT),
        patron_warmup_path=_env_path("KBMTI_PATRON_WARMUP", DEFAULT_PATRON_WARMUP),
        patron_config_path=_env_path("KBMTI_PATRON_CONFIG", DEFAULT_PATRON_CONFIG),
        patron_threads=max(1, _env_int("KBMTI_PATRON_THREADS", 4)),
        patron_history_bars=max(480, _env_int("KBMTI_PATRON_HISTORY_BARS", 520)),
        forecast_auto_enabled=_env_bool("KBMTI_FORECAST_AUTO_ENABLED", True),
        forecast_poll_seconds=max(2.0, _env_float("KBMTI_FORECAST_POLL_SECONDS", 5.0)),
        forecast_history_bars=max(480, _env_int("KBMTI_FORECAST_HISTORY_BARS", 520)),
    )
