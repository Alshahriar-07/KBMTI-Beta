import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { useMarketStream } from "@/hooks/useMarketStream";
import { usePolling } from "@/hooks/usePolling";
import { ApiError, api } from "@/lib/api";
import type {
  AppSettings,
  MarketProvider as MarketProviderId,
  SettingsPatch,
  SymbolList,
  TimeframeOption,
} from "@/lib/types";
import { MarketContext } from "@/state/market-context";

export function MarketProvider({ children }: { children: ReactNode }) {
  const stream = useMarketStream();
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);

  const loadSettings = useCallback(async () => {
    try {
      const next = await api.settings();
      setSettings(next);
      setSettingsError(null);
    } catch (cause) {
      setSettingsError(
        cause instanceof ApiError ? cause.message : "Could not load application settings.",
      );
    } finally {
      setSettingsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  const timeframesResult = usePolling<TimeframeOption[]>("timeframes", () => api.timeframes(), 0);
  const provider = settings?.provider ?? stream.status?.provider ?? "binance";
  const providerLabel =
    settings?.provider_label ??
    stream.status?.provider_label ??
    (provider === "mt5" ? "MetaTrader 5" : "Binance");
  const connected = stream.status?.connected ?? false;
  const timeframes = timeframesResult.data ?? FALLBACK_TIMEFRAMES;

  const symbolsResult = usePolling<SymbolList>(
    `symbols:${provider}:${connected ? "connected" : "offline"}`,
    () => api.symbols(false),
    20_000,
  );

  const runAction = useCallback(
    async (action: () => Promise<unknown>) => {
      try {
        await action();
        setActionError(null);
        await loadSettings();
      } catch (cause) {
        setActionError(
          cause instanceof ApiError ? cause.message : "The action could not be completed.",
        );
      }
    },
    [loadSettings],
  );

  const selectSymbol = useCallback(
    (symbol: string) => runAction(() => api.selectSymbol(symbol)),
    [runAction],
  );

  const selectTimeframe = useCallback(
    (timeframe: string) => runAction(() => api.selectTimeframe(timeframe)),
    [runAction],
  );

  const selectProvider = useCallback(
    (nextProvider: MarketProviderId) =>
      runAction(async () => {
        await api.selectProvider(nextProvider);
        symbolsResult.reload();
      }),
    [runAction, symbolsResult],
  );

  const refreshMarket = useCallback(() => runAction(() => api.refreshMarket()), [runAction]);
  const connectMarket = useCallback(
    () =>
      runAction(async () => {
        await api.connectMarket();
        symbolsResult.reload();
      }),
    [runAction, symbolsResult],
  );
  const disconnectMarket = useCallback(
    () => runAction(() => api.disconnectMarket()),
    [runAction],
  );
  const reconnectMarket = useCallback(
    () =>
      runAction(async () => {
        await api.reconnectMarket();
        symbolsResult.reload();
      }),
    [runAction, symbolsResult],
  );

  const saveSettings = useCallback(
    async (patch: SettingsPatch) => {
      const next = await api.patchSettings(patch);
      setSettings(next);
      if (patch.provider) symbolsResult.reload();
      return next;
    },
    [symbolsResult],
  );

  const value = useMemo(
    () => ({
      stream: {
        status: stream.status,
        snapshot: stream.snapshot,
        forecast: stream.forecast,
        latestForecast: stream.latestForecast,
        transport: stream.transport,
        lastEventAt: stream.lastEventAt,
      },
      settings,
      settingsError: actionError ?? settingsError,
      settingsLoading,
      provider,
      providerLabel,
      symbols: symbolsResult.data,
      symbolsLoading: symbolsResult.loading,
      timeframes,
      selectSymbol,
      selectTimeframe,
      selectProvider,
      refreshMarket,
      connectMarket,
      disconnectMarket,
      reconnectMarket,
      saveSettings,
      reloadSettings: loadSettings,
    }),
    [
      actionError,
      connectMarket,
      disconnectMarket,
      loadSettings,
      provider,
      providerLabel,
      reconnectMarket,
      refreshMarket,
      saveSettings,
      selectProvider,
      selectSymbol,
      selectTimeframe,
      settings,
      settingsError,
      settingsLoading,
      stream.forecast,
      stream.latestForecast,
      stream.lastEventAt,
      stream.snapshot,
      stream.status,
      stream.transport,
      symbolsResult.data,
      symbolsResult.loading,
      timeframes,
    ],
  );

  return <MarketContext.Provider value={value}>{children}</MarketContext.Provider>;
}

const FALLBACK_TIMEFRAMES: TimeframeOption[] = [
  { value: "M1", label: "1 minute", seconds: 60 },
  { value: "M5", label: "5 minutes", seconds: 300 },
  { value: "M15", label: "15 minutes", seconds: 900 },
  { value: "M30", label: "30 minutes", seconds: 1800 },
  { value: "H1", label: "1 hour", seconds: 3600 },
  { value: "H4", label: "4 hours", seconds: 14400 },
  { value: "D1", label: "1 day", seconds: 86400 },
];
