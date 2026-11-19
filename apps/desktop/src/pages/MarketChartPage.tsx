import { AlertTriangle } from "lucide-react";

import { ChartWorkspace } from "@/components/market/ChartWorkspace";
import { usePolling } from "@/hooks/usePolling";
import { api } from "@/lib/api";
import { formatNumber, formatPrice } from "@/lib/format";
import { TONE_DOT, TONE_TEXT, macdState, rsiState } from "@/lib/market";
import type { CandleSeries, Indicators } from "@/lib/types";
import { useMarket } from "@/state/market-context";
import { cn } from "@/lib/utils";

export function MarketChartPage() {
  const { stream, settings } = useMarket();
  const snapshot = stream.snapshot;
  const symbol = settings?.symbol ?? snapshot?.symbol ?? "";
  const timeframe = settings?.timeframe ?? snapshot?.timeframe ?? "M15";
  const limit = settings?.candle_limit ?? 500;
  const digits = snapshot?.digits ?? 2;
  const candleTime = snapshot?.candle_time ?? 0;

  const candles = usePolling<CandleSeries>(
    `chart-candles:${symbol}:${timeframe}:${candleTime}`,
    () => api.candles(limit),
    6000,
  );
  const indicators = usePolling<Indicators>(
    `chart-indicators:${symbol}:${timeframe}:${candleTime}`,
    () => api.indicators(limit),
    15_000,
  );

  const latest = indicators.data?.latest ?? {};
  const rsi = rsiState(latest.rsi14);
  const macd = macdState(latest.macd);
  const error = candles.error ?? indicators.error;

  const readings = [
    { label: "EMA 9", value: formatPrice(latest.ema9, digits), hint: "fast" },
    { label: "EMA 21", value: formatPrice(latest.ema21, digits), hint: "mid" },
    { label: "EMA 50", value: formatPrice(latest.ema50, digits), hint: "slow" },
    {
      label: "RSI 14",
      value: formatNumber(latest.rsi14),
      hint: rsi.label,
      tone: rsi.tone,
    },
    {
      label: "MACD",
      value: formatNumber(latest.macd),
      hint: macd.label,
      tone: macd.tone,
    },
    { label: "ATR 14", value: formatNumber(latest.atr14), hint: "range" },
  ];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ChartWorkspace
        candles={candles.data}
        indicators={indicators.data}
        loading={candles.loading || indicators.loading}
        className="min-h-0 flex-1"
      />

      <section className="grid h-[78px] shrink-0 grid-cols-3 divide-x divide-line border-t border-line bg-surface md:grid-cols-6">
        {readings.map((item) => (
          <div key={item.label} className="flex min-w-0 flex-col justify-center px-3">
            <p className="text-[9.5px] font-medium text-ink-faint">{item.label}</p>
            <p className="num mt-0.5 truncate text-[13px] text-ink-muted">{item.value}</p>
            <p className="mt-0.5 flex items-center gap-1.5 truncate text-[9.5px] text-ink-faint">
              {"tone" in item && item.tone && (
                <span className={cn("size-1 rounded-full", TONE_DOT[item.tone])} />
              )}
              <span className={cn("tone" in item && item.tone && TONE_TEXT[item.tone])}>
                {item.hint}
              </span>
            </p>
          </div>
        ))}
      </section>

      <div className="flex h-[26px] shrink-0 items-center gap-4 border-t border-line-soft bg-surface px-3 text-[9px] text-ink-faint">
        <span>Warm-up {indicators.data?.warmup_bars ?? 0} bars</span>
        <span>{indicators.data?.candle_count ?? 0} computed bars</span>
        <span>Source {candles.data?.source ?? "mt5"}</span>
        <span className="hidden xl:inline">Time basis {indicators.data?.time_basis ?? "utc"}</span>
        <span className="ml-auto inline-flex items-center gap-1.5">
          <span
            className={cn(
              "size-1 rounded-full",
              indicators.data?.data_state === "live" ? "bg-primary" : "bg-warn",
            )}
          />
          {indicators.data?.data_state ?? "unavailable"}
        </span>
      </div>

      {error && (
        <div className="flex shrink-0 items-start gap-2 border-t border-warn/20 bg-warn/[0.04] px-3 py-1.5 text-[10px] text-warn/90">
          <AlertTriangle className="mt-[1px] size-3 shrink-0" aria-hidden />
          <p className="leading-relaxed">{error}</p>
        </div>
      )}
    </div>
  );
}
