import { useState } from "react";
import { AlertTriangle } from "lucide-react";

import { BottomIntelligence } from "@/components/market/BottomIntelligence";
import { ChartWorkspace } from "@/components/market/ChartWorkspace";
import { MarketIntelligence } from "@/components/market/MarketIntelligence";
import { usePolling } from "@/hooks/usePolling";
import { ApiError, api } from "@/lib/api";
import { newestForecast } from "@/lib/forecast";
import type {
  CandleSeries,
  ForecastRun,
  ForecastStatus,
  Indicators,
  PatronStatus,
  Signal,
} from "@/lib/types";
import { useMarket } from "@/state/market-context";

export function OverviewPage() {
  const { stream, settings } = useMarket();
  const snapshot = stream.snapshot;
  const symbol = settings?.symbol ?? snapshot?.symbol ?? "";
  const timeframe = settings?.timeframe ?? snapshot?.timeframe ?? "M15";
  const limit = settings?.candle_limit ?? 500;
  const candleTime = snapshot?.candle_time ?? 0;

  const candles = usePolling<CandleSeries>(
    `overview-candles:${symbol}:${timeframe}:${stream.transport === "open" ? "open" : "down"}`,
    () => api.candles(limit),
    60_000,
  );
  const indicators = usePolling<Indicators>(
    `overview-indicators:${symbol}:${timeframe}:${candleTime}`,
    () => api.indicators(limit),
    20_000,
  );
  const signal = usePolling<Signal>(
    `overview-signal:${symbol}:${timeframe}:${candleTime}`,
    () => api.signal(),
    15_000,
  );
  const patron = usePolling<PatronStatus>("overview-patron", () => api.patronStatus(), 2_000);
  const latest = usePolling<ForecastRun | null>(
    "overview-forecast-latest",
    () => api.forecastLatest(),
    20_000,
  );
  const forecastStatus = usePolling<ForecastStatus>(
    "overview-forecast-status",
    () => api.forecastStatus(),
    10_000,
  );
  // The socket event and the polling fallback can race. Always render the
  // newest persisted run so a new prediction is never hidden by an old hello.
  const latestForecast = newestForecast(stream.latestForecast, latest.data);
  const forecast = forecastStatus.data ?? stream.forecast;
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const runForecast = async () => {
    setRunning(true);
    setRunError(null);
    try {
      await api.runForecast({ symbol: "BTCUSDT", timeframe: "M15", horizon: 6 });
      latest.reload();
      forecastStatus.reload();
      patron.reload();
    } catch (cause) {
      setRunError(cause instanceof ApiError ? cause.message : "Forecast run failed.");
    } finally {
      setRunning(false);
    }
  };

  const error = candles.error ?? indicators.error ?? signal.error ?? runError;

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <ChartWorkspace
          candles={candles.data}
          indicators={indicators.data}
          loading={candles.loading || indicators.loading}
          className="min-h-0 flex-1"
        />

        {error && (
          <div className="flex shrink-0 items-start gap-2 border-t border-warn/20 bg-warn/[0.04] px-3 py-1.5 text-[10px] text-warn/90">
            <AlertTriangle className="mt-[1px] size-3 shrink-0" aria-hidden />
            <p className="leading-relaxed">{error}</p>
          </div>
        )}

        <div className="h-[176px] shrink-0">
          <BottomIntelligence
            forecast={forecast}
            latest={latestForecast}
            patron={patron.data}
            running={running}
            onRun={() => void runForecast()}
            currentCandle={
              stream.status?.provider === "binance" && timeframe === "M15"
                ? (snapshot?.last_candle ?? snapshot?.forming_candle ?? null)
                : null
            }
          />
        </div>
      </div>

      <MarketIntelligence
        snapshot={snapshot}
        status={stream.status}
        indicators={indicators.data}
        signal={signal.data}
        forecast={latestForecast}
        evaluatedAt={forecast?.automation?.last_evaluated_at}
        loading={candles.loading}
      />
    </div>
  );
}
