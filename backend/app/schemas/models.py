"""Pydantic API contracts shared by the FastAPI routers and documented in docs/API_CONTRACTS.md."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    app: str
    version: str
    stage: int
    uptime_seconds: int
    started_at: str
    database: str
    patron: dict[str, Any] | None = None


class TerminalInfo(BaseModel):
    name: str | None = None
    company: str | None = None
    path: str | None = None
    data_path: str | None = None
    common_data_path: str | None = None
    build: int | None = None
    language: int | None = None
    maxbars: int | None = None
    connected: bool | None = None
    trade_allowed: bool | None = None
    dlls_allowed: bool | None = None
    community_connected: bool | None = None
    ping_last: int | None = None


class MT5Status(BaseModel):
    stage: int
    provider: str | None = None
    provider_label: str | None = None
    selected_provider: str | None = None
    providers: dict[str, Any] = Field(default_factory=dict)
    rest_connected: bool | None = None
    ws_connected: bool | None = None
    state: str = "NOT_CONFIGURED"
    state_label: str | None = None
    state_reason: str | None = None
    operational: bool = False
    package_available: bool
    package_version: str | None = None
    connected: bool
    terminal_connected: bool = False
    broker_connected: bool = False
    account_available: bool = False
    symbol_available: bool = False
    tick_available: bool = False
    history_available: bool = False
    market_data_ready: bool = False
    terminal: dict[str, Any] = Field(default_factory=dict)
    terminal_paths: list[str] = Field(default_factory=list)
    terminal_candidates: list[dict[str, Any]] = Field(default_factory=list)
    configured_terminal_path: str | None = None
    resolved_terminal_path: str | None = None
    account: dict[str, Any] = Field(default_factory=dict)
    selected_symbol: str | None = None
    symbol_info: dict[str, Any] = Field(default_factory=dict)
    symbol_error: str | None = None
    timeframe: str
    last_error: str | None = None
    last_error_code: int | None = None
    last_error_description: str | None = None
    last_error_stage: str | None = None
    last_error_detail: dict[str, Any] | None = None
    reconnect_attempts: int = 0
    next_retry_seconds: int = 0
    poll_interval_seconds: float
    connect_timeout_ms: int = 15_000
    stale_after_seconds: float
    freshness: str
    freshness_reason: str | None = None
    time_basis: str
    server_offset_seconds: int | None = None
    candle_count: int = 0
    history_requested: int = 0
    history_returned: int = 0
    history_warnings: list[str] = Field(default_factory=list)
    last_successful_update: str | None = None
    last_tick_at: str | None = None
    last_history_at: str | None = None
    warnings: list[str] = Field(default_factory=list)
    ai_available: bool = False
    uptime_seconds: int


class SymbolInfo(BaseModel):
    name: str
    description: str | None = None
    path: str | None = None
    digits: int | None = None
    point: float | None = None
    volume_min: float | None = None
    volume_step: float | None = None
    spread: int | None = None
    trade_mode: int | None = None
    trade_mode_label: str | None = None
    currency_base: str | None = None
    currency_profit: str | None = None
    visible: bool | None = None
    bid: float | None = None
    ask: float | None = None
    match_score: int | None = None
    match_reason: str | None = None
    recommended: bool | None = None
    btc_like: bool | None = None
    extra: dict[str, Any] | None = None


class SymbolListResponse(BaseModel):
    connected: bool
    state: str | None = None
    symbols: list[dict[str, Any]] = Field(default_factory=list)
    count: int
    total_broker_symbols: int = 0
    selected_symbol: str | None = None
    error: str | None = None
    note: str | None = None
    fetched_at: str | None = None


class CandleModel(BaseModel):
    time: int
    server_time: int | None = None
    open: float
    high: float
    low: float
    close: float
    tick_volume: int = 0
    spread: int = 0
    real_volume: int = 0
    source: str | None = None
    symbol: str | None = None


class CandleSeriesResponse(BaseModel):
    symbol: str | None
    timeframe: str
    provider: str | None = None
    provider_label: str | None = None
    count: int
    candles: list[CandleModel] = Field(default_factory=list)
    forming_candle: CandleModel | None = None
    source: str
    connected: bool
    data_state: str
    stale_reason: str | None = None
    time_basis: str
    server_offset_seconds: int | None = None
    warnings: list[str] = Field(default_factory=list)
    tick_volume_note: str
    history_requested: int = 0
    history_returned: int = 0
    fetched_at: str


class SnapshotResponse(BaseModel):
    provider: str | None = None
    provider_label: str | None = None
    source: str | None = None
    connected: bool
    state: str = "NOT_CONFIGURED"
    operational: bool = False
    state_reason: str | None = None
    symbol: str | None = None
    symbol_description: str | None = None
    timeframe: str
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    spread_points: int | None = None
    spread_price: float | None = None
    digits: int | None = None
    point: float | None = None
    tick_time: int | None = None
    tick_time_server: int | None = None
    tick_time_iso: str | None = None
    tick_lag_seconds: float | None = None
    candle_time: int | None = None
    candle_time_iso: str | None = None
    forming_candle_time: int | None = None
    forming_candle: CandleModel | None = None
    last_candle: CandleModel | None = None
    last_kline_at: str | None = None
    last_kline_latency_ms: float | None = None
    tick_volume: int | None = None
    daily_change: float | None = None
    daily_change_percent: float | None = None
    daily_reference_close: float | None = None
    daily_reference_time: str | None = None
    candle_count: int = 0
    data_state: str
    stale_reason: str | None = None
    last_update: str
    last_successful_update: str | None = None
    server_offset_seconds: int | None = None
    time_basis: str
    tick_volume_note: str
    warnings: list[str] = Field(default_factory=list)
    candle_source: str


class IndicatorSeriesPoint(BaseModel):
    time: int
    value: float


class IndicatorsResponse(BaseModel):
    symbol: str | None
    timeframe: str
    candle_count: int
    last_candle_time_iso: str | None = None
    series: dict[str, list[IndicatorSeriesPoint]] = Field(default_factory=dict)
    latest: dict[str, float | None] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    warmup_bars: int
    data_state: str
    warnings: list[str] = Field(default_factory=list)
    time_basis: str


class SignalFactorModel(BaseModel):
    id: str
    label: str
    detail: str
    weight: float
    direction: str


class SignalResponse(BaseModel):
    symbol: str
    timeframe: str
    label: str
    direction: str
    score: float
    generated_at: str
    data_as_of: str | None = None
    freshness: str
    supporting: list[SignalFactorModel] = Field(default_factory=list)
    conflicting: list[SignalFactorModel] = Field(default_factory=list)
    neutral: list[SignalFactorModel] = Field(default_factory=list)
    invalidation: list[str] = Field(default_factory=list)
    metrics: dict[str, float | None] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    source_candle_count: int
    engine: str
    ai_available: bool = False
    ai_note: str
    disclaimer: str


class ForecastStatusResponse(BaseModel):
    stage: int
    provider: str
    state: str
    ai_available: bool
    model_id: str
    tokenizer_id: str | None = None
    device: str | None = None
    context_limit: int | None = None
    horizon: int
    message: str
    last_run_at: str | None = None
    progress: float | None = None
    checkpoint: str | None = None
    checkpoint_exists: bool | None = None
    checkpoint_sha256: str | None = None
    trainable_parameters: int | None = None
    torch_version: str | None = None
    patron_version: str | None = None
    loaded_at: str | None = None
    load_ms: float | None = None
    last_inference_at: str | None = None
    last_success_at: str | None = None
    last_latency_ms: float | None = None
    inference_count: int | None = None
    failure_count: int | None = None
    last_error: str | None = None
    contract: dict[str, Any] = Field(default_factory=dict)
    automation: dict[str, Any] = Field(default_factory=dict)


class ForecastRunResponse(BaseModel):
    id: str
    provider: str
    model_id: str
    tokenizer_id: str | None = None
    symbol: str
    timeframe: str
    created_at: str
    input_last_bar_at: int | None = None
    input_candle_count: int
    horizon: int
    latency_ms: float | None = None
    runtime: str | None = None
    status: str
    warnings: list[str] = Field(default_factory=list)
    candles: list[dict[str, Any]] | None = None
    output: dict[str, Any] | None = None
    evaluation: list[dict[str, Any]] = Field(default_factory=list)


class ForecastHistoryResponse(BaseModel):
    runs: list[ForecastRunResponse] = Field(default_factory=list)
    count: int
    evaluation: dict[str, Any] | None = None
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    automation: dict[str, Any] | None = None
    message: str
    ai_available: bool = False
    latest: dict[str, Any] | None = None


class PatronStatusResponse(BaseModel):
    enabled: bool
    state: str
    ready: bool
    ai_available: bool
    provider: str
    model_id: str
    model_version: str
    architecture: str
    device: str
    torch_version: str | None = None
    patron_version: str | None = None
    checkpoint_path: str
    checkpoint_exists: bool
    checkpoint_sha256: str | None = None
    checkpoint_bytes: int | None = None
    config_path: str
    config_exists: bool
    warmup_path: str
    warmup_exists: bool
    sequence_length: int
    feature_count: int
    warmup_bars: int
    horizon_candles: int
    horizon_minutes: int
    trainable_parameters: int | None = None
    threads: int
    loaded_at: str | None = None
    load_ms: float | None = None
    last_inference_at: str | None = None
    last_success_at: str | None = None
    last_latency_ms: float | None = None
    last_status: str | None = None
    last_as_of: str | None = None
    inference_count: int
    failure_count: int
    last_error: str | None = None
    last_error_kind: str | None = None
    message: str


class PatronReadinessResponse(BaseModel):
    ready: bool
    state: str
    ai_available: bool
    model_id: str
    checkpoint_exists: bool
    loaded_at: str | None = None
    load_ms: float | None = None
    message: str
    last_error: str | None = None
    checked_at: str


class ChatMessageResponse(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    context: dict[str, Any] | None = None
    created_at: str


class ChatConversationResponse(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int | None = None


class ChatConversationsResponse(BaseModel):
    conversations: list[ChatConversationResponse] = Field(default_factory=list)


class ChatMessagesResponse(BaseModel):
    conversation_id: str
    messages: list[ChatMessageResponse] = Field(default_factory=list)
    context: dict[str, Any] | None = None


class ChatSuggestion(BaseModel):
    id: str
    label: str
    prompt: str


class ChatSuggestionsResponse(BaseModel):
    suggestions: list[ChatSuggestion] = Field(default_factory=list)
    context_available: bool
    message: str | None = None
    patron_ready: bool | None = None


class CpuInfo(BaseModel):
    percent: float | None = None
    physical_cores: int | None = None
    logical_cores: int | None = None
    frequency_mhz: float | None = None


class MemoryInfo(BaseModel):
    total_bytes: int | None = None
    used_bytes: int | None = None
    available_bytes: int | None = None
    percent: float | None = None


class GpuInfo(BaseModel):
    available: bool
    name: str | None = None
    utilization_percent: float | None = None
    memory_used_mb: float | None = None
    memory_total_mb: float | None = None
    note: str | None = None


class TemperatureInfo(BaseModel):
    available: bool
    celsius: float | None = None
    note: str | None = None


class SystemStatusResponse(BaseModel):
    cpu: CpuInfo
    memory: MemoryInfo
    gpu: GpuInfo
    temperature: TemperatureInfo
    backend: dict[str, Any]
    market: dict[str, Any] = Field(default_factory=dict)
    mt5: dict[str, Any]
    platform: dict[str, Any]
    sampled_at: str


class SettingsResponse(BaseModel):
    symbol: str | None = None
    timeframe: str
    candle_limit: int
    provider: str = "binance"
    provider_label: str = "Binance"
    market: dict[str, Any] = Field(default_factory=dict)
    chart: dict[str, Any]
    data: dict[str, Any]
    mt5: dict[str, Any]
    binance: dict[str, Any] = Field(default_factory=dict)
    ui: dict[str, Any]
    state: str | None = None
    state_label: str | None = None
    state_reason: str | None = None


class SettingsPatch(BaseModel):
    symbol: str | None = None
    timeframe: str | None = None
    candle_limit: int | None = Field(default=None, ge=60, le=1500)
    provider: str | None = None
    chart: dict[str, Any] | None = None
    data: dict[str, Any] | None = None
    mt5: dict[str, Any] | None = None
    binance: dict[str, Any] | None = None
    ui: dict[str, Any] | None = None


class DiagnosticsResponse(BaseModel):
    app: dict[str, Any]
    backend: dict[str, Any]
    python: dict[str, Any]
    platform: dict[str, Any]
    market: dict[str, Any] = Field(default_factory=dict)
    realtime: dict[str, Any] = Field(default_factory=dict)
    patron: dict[str, Any] = Field(default_factory=dict)
    mt5: dict[str, Any]
    database: dict[str, Any]
    logs: dict[str, Any]
    settings: dict[str, Any]
    generated_at: str


class ApiErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ApiErrorResponse(BaseModel):
    error: ApiErrorBody
