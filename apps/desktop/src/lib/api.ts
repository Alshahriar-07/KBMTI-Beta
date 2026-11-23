import type {
  AppSettings,
  AssistantStatus,
  BacktestSummary,
  CandleSeries,
  ChatConversations,
  ChatMessages,
  ChatSendResult,
  ChatSuggestions,
  Diagnostics,
  ForecastHistory,
  ForecastLive,
  ForecastRun,
  DatasetVersion,
  ForecastStatus,
  Health,
  Indicators,
  JournalRecordsResponse,
  KieStatus,
  LearningStatus,
  MarketIntelligence,
  ModelRecord,
  Mt5Status,
  PlanningResult,
  OutcomeSummary,
  PatronHealth,
  PatronReadiness,
  PatronStatus,
  ReplayWindow,
  SettingsPatch,
  Signal,
  Snapshot,
  SymbolList,
  SystemStatus,
  TimeframeOption,
  TradingIntelligence,
} from "@/lib/types";

// The desktop launcher serves the UI and API behind one Vite origin (dev proxy
// or preview proxy), so relative URLs are the safe default. VITE_API_BASE is
// reserved for a future separately hosted frontend.
const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export const WS_URL = (() => {
  if (import.meta.env.VITE_WS_URL) return import.meta.env.VITE_WS_URL as string;
  if (API_BASE) return API_BASE.replace(/^http/, "ws") + "/ws/market";
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/market`;
})();

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly retryable: boolean;

  constructor(
    message: string,
    status: number,
    code: string,
    requestId: string | null = null,
    retryable = status === 0 || status >= 500,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.retryable = retryable;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      ...init,
    });
  } catch {
    throw new ApiError(
      "Cannot reach the local KBMTI backend on 127.0.0.1:8756. Start it, then retry.",
      0,
      "BACKEND_UNREACHABLE",
      null,
      true,
    );
  }

  if (!response.ok) {
    let message = `Request failed with status ${response.status}.`;
    let code = `HTTP_${response.status}`;
    let requestId = response.headers.get("X-Request-ID");
    try {
      const body = (await response.json()) as {
        error?: { message?: string; code?: string; request_id?: string };
        detail?: string;
      };
      if (body.error?.message) message = body.error.message;
      if (body.error?.code) code = body.error.code;
      else if (body.detail) message = body.detail;
      if (body.error?.request_id) requestId = body.error.request_id;
    } catch {
      // Keep the generic message when the body is not JSON.
    }
    if (response.status === 502 || response.status === 504) {
      code = "UPSTREAM_UNAVAILABLE";
      message =
        "The local API gateway lost the backend while processing this request. " +
        "The backend may be restarting or the Qwen runtime may have stopped. " +
        "Your last successful analysis is preserved; retry once the runtime is READY.";
    }
    throw new ApiError(message, response.status, code, requestId, response.status >= 500);
  }

  return (await response.json()) as T;
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export const api = {
  health: () => request<Health>("/api/v1/health"),
  snapshot: () => request<Snapshot>("/api/v1/market/snapshot"),
  candles: (limit = 500) => request<CandleSeries>(`/api/v1/market/candles?limit=${limit}`),
  indicators: (limit = 500) =>
    request<Indicators>(`/api/v1/indicators?limit=${limit}`),
  refreshMarket: () => post<Snapshot>("/api/v1/market/refresh"),
  selectSymbol: (symbol: string) =>
    post<{ selected_symbol: string; btc_like: boolean }>("/api/v1/market/symbol", {
      symbol,
    }),
  selectTimeframe: (timeframe: string) =>
    post<{ timeframe: string }>("/api/v1/market/timeframe", { timeframe }),
  timeframes: () => request<TimeframeOption[]>("/api/v1/market/timeframes"),

  symbols: (refresh = false) =>
    request<SymbolList>(`/api/v1/market/symbols?refresh=${refresh ? "true" : "false"}`),
  provider: () => request<Mt5Status>("/api/v1/market/provider"),
  selectProvider: (provider: "binance" | "mt5") =>
    post<Mt5Status>("/api/v1/market/provider", { provider }),
  connectMarket: () => post<Mt5Status>("/api/v1/market/connect"),
  reconnectMarket: () => post<Mt5Status>("/api/v1/market/reconnect"),
  disconnectMarket: () => post<Mt5Status>("/api/v1/market/disconnect"),

  mt5Status: () => request<Mt5Status>("/api/v1/mt5/status"),
  mt5Symbols: (refresh = false) =>
    request<SymbolList>(`/api/v1/mt5/symbols?refresh=${refresh ? "true" : "false"}`),
  mt5Connect: () => post<Mt5Status>("/api/v1/mt5/connect"),
  mt5Disconnect: () => post<Mt5Status>("/api/v1/mt5/disconnect"),

  signal: () => request<Signal>("/api/v1/signals/current"),
  signalHistory: (limit = 50) =>
    request<{ events: Array<Record<string, unknown>>; count: number }>(
      `/api/v1/signals/history?limit=${limit}`,
    ),

  forecastStatus: () => request<ForecastStatus>("/api/v1/forecast/status"),
  forecastLive: (limit = 60) =>
    request<ForecastLive>(`/api/v1/forecast/live?limit=${limit}`),
  forecastHistory: (limit = 50) =>
    request<ForecastHistory>(`/api/v1/forecast/history?limit=${limit}`),
  forecastLatest: () => request<ForecastRun | null>("/api/v1/forecast/latest"),
  forecastRun: (id: string) => request<ForecastRun>(`/api/v1/forecast/${id}`),
  runForecast: (body?: { symbol?: string; timeframe?: string; horizon?: number }) =>
    post<ForecastRun>("/api/v1/forecast/run", body ?? {}),
  evaluateForecasts: () => post<Record<string, unknown>>("/api/v1/forecast/evaluate"),

  patronStatus: () => request<PatronStatus>("/api/v1/patron/status"),
  patronReadiness: () => request<PatronReadiness>("/api/v1/patron/readiness"),
  patronHealth: () => request<PatronHealth>("/api/v1/patron/health"),
  patronLoad: () => post<PatronStatus>("/api/v1/patron/load"),

  systemStatus: () => request<SystemStatus>("/api/v1/system/status"),
  settings: () => request<AppSettings>("/api/v1/settings"),
  patchSettings: (patch: SettingsPatch) =>
    request<AppSettings>("/api/v1/settings", {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  diagnostics: () => request<Diagnostics>("/api/v1/diagnostics"),
  replayWindow: (start: number, count: number) =>
    request<ReplayWindow>(`/api/v1/replay/window?start=${start}&count=${count}`),

  assistantCurrent: (useQwen = true) =>
    request<TradingIntelligence>(`/api/v1/assistant/current?use_qwen=${useQwen ? "true" : "false"}`),
  marketIntelligence: (useQwen = true, refresh = false) =>
    request<MarketIntelligence>(
      `/api/v1/assistant/market-intelligence?use_qwen=${useQwen ? "true" : "false"}&refresh=${refresh ? "true" : "false"}`,
    ),
  planningCurrent: () => request<PlanningResult>("/api/v1/planning/current"),
  assistantStatus: () => request<AssistantStatus>("/api/v1/assistant/status"),
  kieStatus: () => request<KieStatus>("/api/v1/kie/status"),
  kieLoad: () => post<{ loaded: boolean; status: KieStatus }>("/api/v1/kie/load"),

  journalRecords: () => request<JournalRecordsResponse>("/api/v1/journal/records"),
  journalSummary: () => request<OutcomeSummary>("/api/v1/journal/summary"),
  journalMonitor: (id: string) =>
    request<Record<string, unknown>>(`/api/v1/journal/records/${id}/monitor`),

  learningStatus: () => request<LearningStatus>("/api/v1/learning/status"),
  learningDatasets: () => request<{ datasets: DatasetVersion[]; count: number }>("/api/v1/learning/datasets"),
  learningBacktests: () =>
    request<{ backtests: BacktestSummary[]; count: number }>("/api/v1/learning/backtests"),
  learningModels: () =>
    request<{ models: ModelRecord[]; active: ModelRecord | null; count: number; note: string }>(
      "/api/v1/learning/models",
    ),

  chatSuggestions: () => request<ChatSuggestions>("/api/v1/chat/suggestions"),
  chatConversations: () => request<ChatConversations>("/api/v1/chat/conversations"),
  createConversation: (title?: string) =>
    post<{ id: string; title: string }>("/api/v1/chat/conversations", { title }),
  deleteConversation: (id: string) =>
    request<{ deleted: boolean }>(`/api/v1/chat/conversations/${id}`, {
      method: "DELETE",
    }),
  chatMessages: (id: string) =>
    request<ChatMessages>(`/api/v1/chat/conversations/${id}/messages`),
  sendChatMessage: (id: string, content: string) =>
    post<ChatSendResult>(`/api/v1/chat/conversations/${id}/messages`, { content }),
  clearChatMessages: (id: string) =>
    request<{ cleared: number }>(`/api/v1/chat/conversations/${id}/messages`, {
      method: "DELETE",
    }),
};
