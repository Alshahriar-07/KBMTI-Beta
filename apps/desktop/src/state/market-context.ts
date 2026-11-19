import { createContext, useContext } from "react";

import type { TransportState } from "@/hooks/useMarketStream";
import type {
  AppSettings,
  ForecastRun,
  ForecastStatus,
  MarketProvider,
  Mt5Status,
  SettingsPatch,
  Snapshot,
  SymbolList,
  TimeframeOption,
} from "@/lib/types";

export interface MarketContextValue {
  stream: {
    status: Mt5Status | null;
    snapshot: Snapshot | null;
    forecast: ForecastStatus | null;
    latestForecast: ForecastRun | null;
    transport: TransportState;
    lastEventAt: Date | null;
  };
  settings: AppSettings | null;
  settingsError: string | null;
  settingsLoading: boolean;
  provider: MarketProvider | string;
  providerLabel: string;
  symbols: SymbolList | null;
  symbolsLoading: boolean;
  timeframes: TimeframeOption[];
  selectSymbol: (symbol: string) => Promise<void>;
  selectTimeframe: (timeframe: string) => Promise<void>;
  selectProvider: (provider: MarketProvider) => Promise<void>;
  refreshMarket: () => Promise<void>;
  connectMarket: () => Promise<void>;
  disconnectMarket: () => Promise<void>;
  reconnectMarket: () => Promise<void>;
  saveSettings: (patch: SettingsPatch) => Promise<AppSettings>;
  reloadSettings: () => Promise<void>;
}

export const MarketContext = createContext<MarketContextValue | null>(null);

export function useMarket(): MarketContextValue {
  const value = useContext(MarketContext);
  if (!value) {
    throw new Error("useMarket must be used inside <MarketProvider>.");
  }
  return value;
}
