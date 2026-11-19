export type Timestamp = number;

export type MarketProvider = "binance" | "mt5";

export interface Candle {
  time: Timestamp;
  open: number;
  high: number;
  low: number;
  close: number;
  tick_volume: number;
  spread: number;
  real_volume: number;
  source?: string | null;
  symbol?: string | null;
}

export interface CandleSeries {
  symbol: string | null;
  timeframe: string;
  provider?: MarketProvider | string | null;
  count: number;
  candles: Candle[];
  forming_candle: Candle | null;
  source: string;
  connected: boolean;
  data_state: string;
  stale_reason: string | null;
  time_basis: string;
  warnings: string[];
  tick_volume_note: string;
  fetched_at: string;
}

export interface Snapshot {
  provider?: MarketProvider | string | null;
  provider_label?: string | null;
  source?: string | null;
  connected: boolean;
  symbol: string | null;
  symbol_description: string | null;
  timeframe: string;
  bid: number | null;
  ask: number | null;
  last: number | null;
  spread_points: number | null;
  spread_price: number | null;
  digits: number | null;
  point: number | null;
  tick_time: number | null;
  tick_time_iso: string | null;
  tick_lag_seconds: number | null;
  candle_time: number | null;
  candle_time_iso: string | null;
  forming_candle_time: number | null;
  forming_candle?: Candle | null;
  last_candle?: Candle | null;
  last_kline_at?: string | null;
  last_kline_latency_ms?: number | null;
  tick_volume: number | null;
  daily_change: number | null;
  daily_change_percent: number | null;
  daily_reference_close: number | null;
  daily_reference_time: string | null;
  data_state: string;
  stale_reason: string | null;
  last_update: string;
  time_basis: string;
  tick_volume_note: string;
  warnings: string[];
  candle_source: string;
}

export interface ProviderSummary {
  provider: MarketProvider | string;
  provider_label: string;
  connected: boolean;
  state: string;
  state_label?: string | null;
  state_reason?: string | null;
  freshness?: string | null;
  selected_symbol?: string | null;
  last_error?: string | null;
  last_successful_update?: string | null;
  ws_connected?: boolean | null;
}

export interface Mt5Status {
  stage: number;
  provider?: MarketProvider | string | null;
  provider_label?: string | null;
  selected_provider?: MarketProvider | string | null;
  providers?: Record<string, ProviderSummary>;
  package_available: boolean;
  package_version: string | null;
  connected: boolean;
  rest_connected?: boolean | null;
  ws_connected?: boolean | null;
  terminal_connected?: boolean | null;
  broker_connected?: boolean | null;
  account_available?: boolean | null;
  terminal: Record<string, unknown>;
  terminal_paths: string[];
  selected_symbol: string | null;
  symbol_info: Record<string, unknown>;
  symbol_error?: string | null;
  timeframe: string;
  last_error: string | null;
  last_error_stage?: string | null;
  reconnect_attempts: number;
  next_retry_seconds: number;
  poll_interval_seconds: number;
  stale_after_seconds: number;
  freshness: string;
  freshness_reason: string | null;
  time_basis: string;
  candle_count?: number;
  last_successful_update?: string | null;
  last_tick_at?: string | null;
  last_history_at?: string | null;
  warnings: string[];
  ai_available: boolean;
  uptime_seconds: number;
}

export interface IndicatorPoint {
  time: Timestamp;
  value: number;
}

export interface Indicators {
  symbol: string | null;
  timeframe: string;
  candle_count: number;
  last_candle_time_iso: string | null;
  series: Record<string, IndicatorPoint[]>;
  latest: Record<string, number | null>;
  parameters: Record<string, unknown>;
  warmup_bars: number;
  data_state: string;
  warnings: string[];
  time_basis: string;
}

export interface SignalFactor {
  id: string;
  label: string;
  detail: string;
  weight: number;
  direction: string;
}

export interface Signal {
  symbol: string;
  timeframe: string;
  label: string;
  direction: string;
  score: number;
  generated_at: string;
  data_as_of: string | null;
  freshness: string;
  supporting: SignalFactor[];
  conflicting: SignalFactor[];
  neutral: SignalFactor[];
  invalidation: string[];
  metrics: Record<string, number | null>;
  warnings: string[];
  source_candle_count: number;
  engine: string;
  ai_available: boolean;
  ai_note: string;
  disclaimer: string;
}

export interface ForecastAutomation {
  enabled: boolean;
  running: boolean;
  poll_seconds?: number;
  recovery_seconds?: number;
  mode?: string;
  state?: string;
  cycles?: number;
  forecasts?: number;
  skipped?: number;
  steps_evaluated?: number;
  failures?: number;
  last_cycle_at?: string | null;
  last_forecast_at?: string | null;
  last_forecast_bar_at?: string | null;
  last_evaluated_at?: string | null;
  last_error?: string | null;
  evaluation_error?: string | null;
  waiting_for?: string | null;
  last_trigger_at?: string | null;
  last_trigger_bar_at?: string | null;
  queue_wait_ms?: number | null;
  evaluation_ms?: number | null;
  forecast_ms?: number | null;
  inference_ms?: number | null;
  cycle_ms?: number | null;
  trigger_to_forecast_ms?: number | null;
  message?: string;
}

export interface ForecastStatus {
  stage: number;
  provider: string;
  state: string;
  ai_available: boolean;
  model_id: string;
  tokenizer_id: string | null;
  device: string | null;
  context_limit: number | null;
  horizon: number;
  message: string;
  last_run_at: string | null;
  progress: number | null;
  checkpoint?: string | null;
  checkpoint_exists?: boolean | null;
  checkpoint_sha256?: string | null;
  trainable_parameters?: number | null;
  torch_version?: string | null;
  patron_version?: string | null;
  loaded_at?: string | null;
  load_ms?: number | null;
  last_inference_at?: string | null;
  last_success_at?: string | null;
  last_latency_ms?: number | null;
  inference_count?: number | null;
  failure_count?: number | null;
  last_error?: string | null;
  contract?: Record<string, unknown>;
  automation?: ForecastAutomation;
}

export interface PatronStatus {
  enabled: boolean;
  state: string;
  ready: boolean;
  ai_available: boolean;
  provider: string;
  model_id: string;
  model_version: string;
  architecture: string;
  device: string;
  torch_version: string | null;
  patron_version: string | null;
  checkpoint_path: string;
  checkpoint_exists: boolean;
  checkpoint_sha256: string | null;
  checkpoint_bytes: number | null;
  config_path: string;
  config_exists: boolean;
  warmup_path: string;
  warmup_exists: boolean;
  sequence_length: number;
  feature_count: number;
  warmup_bars: number;
  horizon_candles: number;
  horizon_minutes: number;
  trainable_parameters: number | null;
  threads: number;
  loaded_at: string | null;
  load_ms: number | null;
  last_inference_at: string | null;
  last_success_at: string | null;
  last_latency_ms: number | null;
  last_status: string | null;
  last_as_of: string | null;
  inference_count: number;
  failure_count: number;
  last_error: string | null;
  last_error_kind: string | null;
  message: string;
}

export interface PatronReadiness {
  ready: boolean;
  state: string;
  ai_available: boolean;
  model_id: string;
  checkpoint_exists: boolean;
  loaded_at: string | null;
  load_ms: number | null;
  message: string;
  last_error: string | null;
  checked_at: string;
}

export interface PatronHealth {
  healthy: boolean;
  status: string;
  checks: Array<{ id: string; label: string; ok: boolean; status: string; detail: string }>;
  state: string;
  ready: boolean;
  message: string;
  last_success_at: string | null;
  last_error: string | null;
  checked_at: string;
}

export interface QuantileTriplet {
  q10: number;
  q50: number;
  q90: number;
}

export interface ForecastQuantileStep {
  step: number;
  minutes_ahead: number;
  high: QuantileTriplet;
  low: QuantileTriplet;
  close: QuantileTriplet;
}

export interface PatronOutput {
  status: string;
  symbol: string;
  as_of: string;
  horizon_minutes: number;
  model_version: string;
  feature_version: string;
  pattern_scores: Record<string, number>;
  barrier_probabilities: { tp_first: number; sl_first: number; timeout: number };
  range_quantiles: ForecastQuantileStep[];
  momentum: { class_probabilities: Record<string, number>; predicted_class: string };
  data_quality: { valid: boolean; closed_candles: number; sequence_length: number; warnings: string[] };
}

export interface ForecastOutputMeta {
  reference_close?: number | null;
  reference_close_time?: string | null;
  last_input_open_time?: string | null;
  checkpoint?: string;
  checkpoint_sha256?: string | null;
  history_bars_used?: number;
  warmup_bars?: number;
  patron_latency_ms?: number;
  derivation?: string;
}

export interface ForecastOutput {
  patron?: PatronOutput;
  meta?: ForecastOutputMeta;
}

export interface ForecastEvaluationStep {
  step: number;
  target_ts: number;
  target_time?: string;
  forecast_run_id?: string;
  model_id?: string;
  created_at?: string;
  actual_open?: number | null;
  actual_high?: number | null;
  actual_low?: number | null;
  actual_close: number;
  predicted_open?: number | null;
  predicted_high?: number | null;
  predicted_low?: number | null;
  predicted_close: number;
  open_abs_error?: number | null;
  high_abs_error?: number | null;
  low_abs_error?: number | null;
  abs_error: number;
  pct_error: number;
  predicted_direction?: string | null;
  actual_direction?: string | null;
  direction_correct: boolean;
  success: boolean;
  in_band: boolean;
  evaluated_at: string;
}

export interface ForecastLastEvaluation {
  target_ts: number;
  target_time: string;
  actual_direction: string | null;
  predicted_direction: string | null;
  success: boolean;
  abs_error: number;
  actual_close: number;
  predicted_close: number;
}

export interface ForecastEvaluationSummary {
  runs_evaluated: number;
  steps_evaluated: number;
  successful: number;
  failed: number;
  close_mae: number | null;
  close_mape: number | null;
  direction_accuracy: number | null;
  bullish_accuracy: number | null;
  bearish_accuracy: number | null;
  band_coverage: number | null;
  last_evaluated: ForecastLastEvaluation | null;
  doji_threshold: number;
}

export interface ForecastRun {
  id: string;
  provider: string;
  model_id: string;
  tokenizer_id: string | null;
  symbol: string;
  timeframe: string;
  created_at: string;
  input_last_bar_at: number | null;
  input_candle_count: number;
  horizon: number;
  latency_ms: number | null;
  runtime: string | null;
  status: string;
  warnings: string[];
  candles?: Array<{
    sequence: number;
    timestamp_utc: number;
    open: number;
    high: number;
    low: number;
    close: number;
  }> | null;
  output?: ForecastOutput | null;
  evaluation?: ForecastEvaluationStep[];
}

export interface ForecastHistory {
  runs: ForecastRun[];
  count: number;
  evaluation: ForecastEvaluationSummary | null;
  timeline: ForecastEvaluationStep[];
  automation?: ForecastAutomation | null;
  message: string;
  ai_available: boolean;
  latest?: ForecastRun | null;
}

export interface ForecastMarketContext {
  provider: string | null;
  symbol: string | null;
  timeframe: string | null;
  last: number | null;
  daily_change_percent: number | null;
  data_state: string;
  connected: boolean;
  live: boolean;
  as_of: string | null;
}

export interface ForecastLive {
  symbol: string;
  timeframe: string;
  bar_seconds: number;
  candles: Candle[];
  forming_candle: Candle | null;
  latest: ForecastRun | null;
  status: ForecastStatus;
  evaluation: ForecastEvaluationSummary;
  timeline: ForecastEvaluationStep[];
  as_of: string;
  data_warning: string | null;
  market: ForecastMarketContext;
}

export interface CpuInfo {
  percent: number | null;
  physical_cores: number | null;
  logical_cores: number | null;
  frequency_mhz: number | null;
}

export interface MemoryInfo {
  total_bytes: number | null;
  used_bytes: number | null;
  available_bytes: number | null;
  percent: number | null;
}

export interface GpuInfo {
  available: boolean;
  name: string | null;
  utilization_percent: number | null;
  memory_used_mb: number | null;
  memory_total_mb: number | null;
  note: string | null;
}

export interface TemperatureInfo {
  available: boolean;
  celsius: number | null;
  note: string | null;
}

export interface SystemStatus {
  cpu: CpuInfo;
  memory: MemoryInfo;
  gpu: GpuInfo;
  temperature: TemperatureInfo;
  backend: Record<string, unknown>;
  market?: Record<string, unknown>;
  mt5: Record<string, unknown>;
  platform: Record<string, unknown>;
  sampled_at: string;
}

export interface ChartSettings {
  show_ema: boolean;
  show_bollinger: boolean;
  show_volume: boolean;
  show_rsi: boolean;
  show_macd: boolean;
  show_atr: boolean;
  crosshair: boolean;
}

export interface MarketDataConfig {
  provider: MarketProvider | string;
  provider_label: string;
  selected_symbol: string | null;
  timeframe: string;
  connected: boolean;
  state: string;
  state_label?: string | null;
  state_reason?: string | null;
  freshness?: string | null;
  freshness_reason?: string | null;
  last_successful_update?: string | null;
  last_error?: string | null;
  ws_connected?: boolean | null;
  rest_connected?: boolean | null;
  providers?: Record<string, ProviderSummary>;
}

export interface Mt5Settings {
  terminal_path?: string | null;
  resolved_path?: string | null;
  default_path?: string | null;
  detected_paths?: string[];
  candidates?: Array<Record<string, unknown>>;
  state?: string | null;
  state_label?: string | null;
  state_reason?: string | null;
  connected?: boolean | null;
  terminal_connected?: boolean | null;
  broker_connected?: boolean | null;
  terminal?: Record<string, unknown>;
  account_available?: boolean | null;
  connect_timeout_ms?: number | null;
  stale_after_seconds?: number | null;
  poll_interval_seconds?: number | null;
  last_error?: string | null;
  freshness?: string | null;
  last_successful_update?: string | null;
}

export interface BinanceSettings {
  symbol?: string | null;
  rest_url?: string | null;
  ws_url?: string | null;
  connected?: boolean | null;
  ws_connected?: boolean | null;
  freshness?: string | null;
  last_error?: string | null;
  last_successful_update?: string | null;
}

export interface AppSettings {
  symbol: string | null;
  timeframe: string;
  candle_limit: number;
  provider: MarketProvider | string;
  provider_label: string;
  market: MarketDataConfig;
  chart: ChartSettings;
  data: Record<string, unknown>;
  mt5: Mt5Settings;
  binance: BinanceSettings;
  ui: Record<string, unknown>;
}

export type SettingsPatch = Partial<{
  symbol: string;
  timeframe: string;
  candle_limit: number;
  provider: MarketProvider;
  chart: Partial<ChartSettings>;
  data: Record<string, unknown>;
  mt5: Record<string, unknown>;
  binance: Record<string, unknown>;
  ui: Record<string, unknown>;
}>;

export interface SymbolEntry {
  name: string;
  description: string | null;
  path: string | null;
  digits: number | null;
  spread: number | null;
  btc_like: boolean | null;
  recommended: boolean | null;
  match_score: number | null;
  match_reason: string | null;
  bid: number | null;
  ask: number | null;
}

export interface SymbolList {
  connected: boolean;
  symbols: SymbolEntry[];
  count: number;
  selected_symbol: string | null;
  error: string | null;
  note: string | null;
  fetched_at: string | null;
}

export interface ChatConversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number | null;
}

export interface ChatMessage {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | string;
  content: string;
  context: Record<string, unknown> | null;
  created_at: string;
}

export interface ChatSuggestion {
  id: string;
  label: string;
  prompt: string;
}

export interface ChatSuggestions {
  suggestions: ChatSuggestion[];
  context_available: boolean;
  message: string | null;
  patron_ready?: boolean | null;
}

export interface ChatConversations {
  conversations: ChatConversation[];
}

export interface ChatMessages {
  conversation_id: string;
  messages: ChatMessage[];
  context: Record<string, unknown> | null;
}

export interface ChatSendResult {
  user_message: ChatMessage;
  assistant_message: ChatMessage;
  context: Record<string, unknown>;
}

export interface Health {
  status: string;
  app: string;
  version: string;
  stage: number;
  uptime_seconds: number;
  started_at: string;
  database: string;
}

export interface ReplayWindow {
  symbol: string | null;
  timeframe: string;
  start_index: number;
  end_index: number;
  total: number;
  candles: Candle[];
  source: string;
  data_state: string;
  time_basis: string;
  ai_available: boolean;
  message: string;
}

export interface Diagnostics {
  app: Record<string, unknown>;
  backend: Record<string, unknown>;
  python: Record<string, unknown>;
  platform: Record<string, unknown>;
  market?: Record<string, unknown>;
  patron?: Record<string, unknown>;
  mt5: Record<string, unknown>;
  realtime?: {
    market?: Record<string, unknown> | null;
    forecast?: ForecastAutomation | null;
  };
  database: Record<string, unknown>;
  logs: { path: string | null; recent: string[] };
  settings: Record<string, unknown>;
  generated_at: string;
}

export interface TimeframeOption {
  value: string;
  label: string;
  seconds: number;
}

export interface StreamCandleEvent {
  symbol: string;
  timeframe: string;
  closed: boolean;
  candle: Candle;
  exchange_event_ms?: number | null;
  received_at: string;
  receive_latency_ms?: number | null;
  close_identity: string;
}

export type StreamEvent =
  | { type: "hello"; payload: StreamHello }
  | { type: "market"; payload: Snapshot }
  | { type: "candle"; payload: StreamCandleEvent }
  | { type: "forecast"; payload: ForecastRun }
  | { type: "status"; payload: Mt5Status }
  | { type: "heartbeat"; payload: { server_time: string } };

export interface StreamHello {
  status: Mt5Status;
  snapshot: Snapshot;
  forecast: ForecastStatus;
  latest_forecast?: ForecastRun | null;
  server_time: string;
}
