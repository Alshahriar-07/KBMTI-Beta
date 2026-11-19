import { BrainCircuit, History, Info, ShieldAlert } from "lucide-react";

import { SignalDistribution } from "@/components/market/SignalDistribution";
import { AiNotice } from "@/components/ui/AiNotice";
import { Badge } from "@/components/ui/Badge";
import { DataRow } from "@/components/ui/DataRow";
import { EmptyState } from "@/components/ui/EmptyState";
import { GroupLabel, Panel } from "@/components/ui/Panel";
import { Spinner } from "@/components/ui/Spinner";
import { usePolling } from "@/hooks/usePolling";
import { api } from "@/lib/api";
import { newestForecast } from "@/lib/forecast";
import { formatBrokerTime, formatNumber, formatPrice } from "@/lib/format";
import type { ForecastRun, Signal, SignalFactor } from "@/lib/types";
import { useMarket } from "@/state/market-context";
import { cn } from "@/lib/utils";

interface SignalEvent {
  id?: string;
  label?: string;
  direction?: string;
  score?: number;
  timeframe?: string;
  freshness?: string;
  generated_at?: string;
  timestamp_iso?: string;
}

function splitFromScore(score: number | undefined): { buy: number; sell: number } {
  const clamped = Math.max(-1, Math.min(1, Number(score ?? 0)));
  const buy = Math.round(((clamped + 1) / 2) * 1000) / 10;
  return { buy, sell: Math.round((100 - buy) * 10) / 10 };
}

function FactorRow({
  factor,
  tone,
}: {
  factor: SignalFactor;
  tone: "bull" | "bear" | "neutral";
}) {
  return (
    <div className="border-b border-line-soft/70 px-3 py-2 last:border-b-0">
      <div className="flex items-baseline justify-between gap-3">
        <p
          className={cn(
            "text-[11px] font-medium",
            tone === "bull" ? "text-bull/90" : tone === "bear" ? "text-bear/90" : "text-ink-muted",
          )}
        >
          {factor.label}
        </p>
        <span className="num shrink-0 text-[9.5px] text-ink-faint">
          {factor.weight > 0 ? "+" : ""}
          {factor.weight.toFixed(2)}
        </span>
      </div>
      <p className="mt-0.5 text-[9.5px] leading-relaxed text-ink-faint">{factor.detail}</p>
    </div>
  );
}

function SubHeader({ children, count }: { children: string; count: number }) {
  return (
    <div className="flex h-6 items-center justify-between gap-2 border-b border-line-soft bg-surface-2/30 px-3">
      <span className="label-xs">{children}</span>
      <span className="num text-[9px] text-ink-faint">{count}</span>
    </div>
  );
}

export function SignalsPage() {
  const { stream, settings } = useMarket();
  const symbol = settings?.symbol ?? stream.snapshot?.symbol ?? "";
  const timeframe = settings?.timeframe ?? stream.snapshot?.timeframe ?? "M15";
  const candleTime = stream.snapshot?.candle_time ?? 0;
  const digits = stream.snapshot?.digits ?? 2;

  const signal = usePolling<Signal>(
    `signals:${symbol}:${timeframe}:${candleTime}`,
    () => api.signal(),
    15_000,
  );
  const patronForecast = usePolling<ForecastRun | null>(
    "signals-patron-forecast",
    () => api.forecastLatest(),
    20_000,
  );
  const history = usePolling<{ events: SignalEvent[]; count: number }>(
    "signal-history",
    () => api.signalHistory(40) as Promise<{ events: SignalEvent[]; count: number }>,
    20_000,
  );
  const modelForecast = newestForecast(stream.latestForecast, patronForecast.data);

  const data = signal.data;
  const metrics = data?.metrics ?? {};
  const events = history.data?.events ?? [];

  return (
    <div className="scroll-area h-full">
      <AiNotice>
        The BUY/SELL split uses PATRON's 90-minute close quantiles from the latest stored
        forecast, falling back to its five-class momentum output and then the technical rule
        score. It is a directional model reading, not a calibrated trade probability.
      </AiNotice>

      <div className="grid border-b border-line bg-surface xl:grid-cols-[minmax(0,1fr)_304px] xl:divide-x xl:divide-line">
        <div className="min-w-0">
          <header className="flex h-[30px] items-center gap-2 border-b border-line-soft px-3">
            <h2 className="label-xs">Signal distribution</h2>
            <span className="num text-[9.5px] text-ink-faint">
              {symbol || "no symbol"} · {timeframe}
            </span>
            <span className="ml-auto flex items-center gap-2">
              {(signal.loading || patronForecast.loading) && <Spinner />}
              <Badge tone="info">Directional model</Badge>
            </span>
          </header>

          {data || modelForecast ? (
            <>
              <div className="border-b border-line-soft px-3 py-3">
                <SignalDistribution signal={data} forecast={modelForecast} />
              </div>

              {data && (
                <div className="grid md:grid-cols-2 md:divide-x md:divide-line">
                  <div>
                    <SubHeader count={data.supporting.length}>Supporting evidence</SubHeader>
                    {data.supporting.length ? (
                      data.supporting.map((factor) => (
                        <FactorRow key={factor.id} factor={factor} tone="bull" />
                      ))
                    ) : (
                      <p className="px-3 py-3 text-[10px] text-ink-faint">
                        No supporting factors at this reading.
                      </p>
                    )}
                  </div>
                  <div>
                    <SubHeader count={data.conflicting.length}>Conflicting evidence</SubHeader>
                    {data.conflicting.length ? (
                      data.conflicting.map((factor) => (
                        <FactorRow key={factor.id} factor={factor} tone="bear" />
                      ))
                    ) : (
                      <p className="px-3 py-3 text-[10px] text-ink-faint">
                        No conflicting factors at this reading.
                      </p>
                    )}
                  </div>
                </div>
              )}

              {data && (
                <div className="border-t border-line-soft px-3 py-2.5">
                  <p className="flex items-center gap-1.5 label-xs">
                    <Info className="size-3" aria-hidden /> Invalidation conditions
                  </p>
                  <ul className="mt-1.5 space-y-1">
                    {data.invalidation.map((line) => (
                      <li
                        key={line}
                        className="flex gap-2 text-[10px] leading-relaxed text-ink-faint"
                      >
                        <span className="mt-[6px] size-1 shrink-0 bg-ink-faint/60" />
                        {line}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          ) : (
            <EmptyState
              icon={BrainCircuit}
              title={signal.loading || patronForecast.loading ? "Reading indicators" : "No signal available"}
              description={
                signal.error ??
                patronForecast.error ??
                "Connect a market feed and let 50 completed candles accumulate before a directional signal is evaluated."
              }
            />
          )}
        </div>

        <aside className="min-w-0 border-t border-line xl:border-t-0">
          <GroupLabel>Reading context</GroupLabel>
          <DataRow label="Last close" value={formatPrice(metrics.close, digits)} />
          <DataRow label="RSI 14" value={formatNumber(metrics.rsi14)} />
          <DataRow label="ATR 14" value={formatNumber(metrics.atr14)} />
          <DataRow
            label="Rule reading"
            value={formatBrokerTime(data?.generated_at, true)}
            hint="UTC"
          />

          <GroupLabel>Neutral factors</GroupLabel>
          {data?.neutral.length ? (
            data.neutral.map((factor) => (
              <FactorRow key={factor.id} factor={factor} tone="neutral" />
            ))
          ) : (
            <p className="px-3 py-2.5 text-[10px] text-ink-faint">No neutral factors recorded.</p>
          )}

          <GroupLabel>Warnings</GroupLabel>
          <div className="space-y-1.5 px-3 py-2.5">
            {data?.warnings.length ? (
              data.warnings.map((warning) => (
                <p
                  key={warning}
                  className="border-l border-warn/40 bg-warn/[0.04] px-2 py-1.5 text-[9.5px] leading-relaxed text-warn/80"
                >
                  {warning}
                </p>
              ))
            ) : (
              <p className="text-[10px] text-ink-faint">No warnings recorded for this reading.</p>
            )}
          </div>

          <div className="border-t border-line-soft px-3 py-2.5">
            <p className="flex items-start gap-1.5 text-[9px] leading-relaxed text-ink-faint">
              <ShieldAlert className="mt-[1px] size-3 shrink-0" aria-hidden />
              Model-generated market analysis. Not a trade instruction and not financial advice.
            </p>
          </div>
        </aside>
      </div>

      <div className="p-3">
        <Panel
          title="Signal history"
          icon={<History className="size-3.5" />}
          meta={`${history.data?.count ?? 0} persisted snapshots`}
          bodyClassName="p-0"
        >
          {events.length ? (
            <div className="scroll-area max-h-[320px]">
              <table className="w-full border-collapse text-left">
                <thead className="sticky top-0 z-10 bg-surface-2">
                  <tr className="text-[9px] text-ink-faint">
                    <th className="h-7 px-3 font-medium">Generated</th>
                    <th className="h-7 px-3 font-medium">Timeframe</th>
                    <th className="h-7 px-3 font-medium">Distribution</th>
                    <th className="h-7 px-3 font-medium">Freshness</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((event, index) => {
                    const split =
                      typeof event.score === "number" ? splitFromScore(event.score) : null;
                    return (
                      <tr
                        key={event.id ?? `${event.generated_at ?? "event"}-${index}`}
                        className="border-t border-line-soft/70 text-[10px] text-ink-muted hover:bg-surface-2/40"
                      >
                        <td className="h-7 px-3">
                          {formatBrokerTime(event.generated_at ?? event.timestamp_iso, true)}
                        </td>
                        <td className="h-7 px-3">{event.timeframe ?? timeframe}</td>
                        <td className="h-7 px-3">
                          {split ? (
                            <span className="inline-flex items-center gap-1.5">
                              <span
                                className={cn(
                                  "size-1 rounded-full",
                                  split.buy >= split.sell
                                    ? "bg-[var(--color-bull)]"
                                    : "bg-[var(--color-bear)]",
                                )}
                              />
                              <span className="num text-[9px] text-ink-muted">
                                BUY {split.buy.toFixed(1)}% · SELL {split.sell.toFixed(1)}%
                              </span>
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="h-7 px-3">{event.freshness ?? "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              icon={History}
              title="No saved signal snapshots"
              description="Snapshots are stored when the rules engine has enough completed candles to evaluate a bias."
            />
          )}
        </Panel>
      </div>
    </div>
  );
}
