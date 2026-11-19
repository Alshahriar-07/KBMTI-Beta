import { ArrowRight, BrainCircuit } from "lucide-react";
import { Link } from "react-router-dom";

import { SignalDistribution } from "@/components/market/SignalDistribution";
import { DataRow } from "@/components/ui/DataRow";
import { GroupLabel } from "@/components/ui/Panel";
import {
  TONE_DOT,
  TONE_TEXT,
  bollingerPosition,
  emaStructure,
  macdState,
  rsiState,
} from "@/lib/market";
import {
  formatBrokerTime,
  formatNumber,
  formatPercent,
  formatPrice,
  formatTimeOnly,
} from "@/lib/format";
import type { ForecastRun, Indicators, Mt5Status, Signal, Snapshot } from "@/lib/types";
import { cn } from "@/lib/utils";

function ReadingRow({
  label,
  readingTone,
  primary,
  detail,
}: {
  label: string;
  readingTone: keyof typeof TONE_TEXT;
  primary: string;
  detail: string;
}) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-line-soft/70 px-3 py-[5px] last:border-b-0">
      <span className="flex min-w-0 items-center gap-1.5">
        <span className={cn("size-1 shrink-0 rounded-full", TONE_DOT[readingTone])} />
        <span className="truncate text-[10.5px] text-ink-faint">{label}</span>
      </span>
      <span className="flex shrink-0 items-baseline gap-1.5">
        <span className="truncate text-[9.5px] text-ink-faint">{detail}</span>
        <span className={cn("num text-[10.5px] font-medium", TONE_TEXT[readingTone])}>
          {primary}
        </span>
      </span>
    </div>
  );
}

interface MarketIntelligenceProps {
  snapshot: Snapshot | null;
  status: Mt5Status | null;
  indicators: Indicators | null;
  signal: Signal | null;
  forecast?: ForecastRun | null;
  evaluatedAt?: string | null;
  loading?: boolean;
}

/** Right-hand structured market rail: quote, feed provenance, technicals, bias. */
export function MarketIntelligence({
  snapshot,
  status,
  indicators,
  signal,
  forecast = null,
  evaluatedAt = null,
  loading = false,
}: MarketIntelligenceProps) {
  const digits = snapshot?.digits ?? 2;
  const change = snapshot?.daily_change_percent ?? null;
  const positive = (change ?? 0) > 0;
  const negative = (change ?? 0) < 0;
  const changeTone = positive ? "text-bull" : negative ? "text-bear" : "text-ink-muted";
  const latest = indicators?.latest ?? {};
  const freshness = snapshot?.data_state ?? status?.freshness ?? "unavailable";
  // ``candle_time`` is the open of the last closed bar. The forming bar's open
  // is the same instant as that bar's close, which is the timestamp users expect.
  const barCloseIso = snapshot?.forming_candle_time
    ? new Date(snapshot.forming_candle_time * 1000).toISOString()
    : (snapshot?.candle_time_iso ?? null);
  const ema = emaStructure(latest);
  const rsi = rsiState(latest.rsi14);
  const macd = macdState(latest.macd);
  const bb = bollingerPosition(latest);

  return (
    <aside className="flex w-[292px] shrink-0 flex-col border-l border-line bg-surface">
      <header className="flex h-[34px] shrink-0 items-center gap-2 border-b border-line-soft px-3">
        <span className="label-xs text-[10.5px]">Market intelligence</span>
        <span
          className={cn(
            "ml-auto size-1.5 rounded-full",
            snapshot?.connected ? "bg-primary" : "bg-warn",
          )}
        />
        <span className="text-[9.5px] text-ink-faint">{loading ? "loading" : freshness}</span>
      </header>

      <div className="scroll-area min-h-0 flex-1">
        <div className="border-b border-line-soft px-3 pt-2.5 pb-2">
          <div className="flex items-baseline justify-between gap-2">
            <span className="num text-[10.5px] font-medium text-ink-muted">
              {snapshot?.symbol ?? status?.selected_symbol ?? "No symbol"}
            </span>
            <span className="text-[9px] text-ink-faint">
              {snapshot?.timeframe ?? "—"} · last
            </span>
          </div>
          <div className="mt-1.5 flex items-baseline gap-2">
            <p className="num text-[24px] leading-none font-semibold tracking-[-0.02em] text-ink">
              {formatPrice(snapshot?.last ?? snapshot?.bid, digits)}
            </p>
            <span className={cn("num text-[11px] font-medium", changeTone)}>
              {positive ? "+" : ""}
              {formatPercent(change)}
            </span>
          </div>
          <p className="mt-1.5 flex items-center justify-between gap-2 text-[9.5px] text-ink-faint">
            <span>Daily reference {formatPrice(snapshot?.daily_reference_close, digits)}</span>
            <span className="num">{formatTimeOnly(snapshot?.tick_time_iso)}</span>
          </p>
        </div>

        <GroupLabel>Top of book</GroupLabel>
        <DataRow label="Bid" value={formatPrice(snapshot?.bid, digits)} />
        <DataRow label="Ask" value={formatPrice(snapshot?.ask, digits)} />
        <DataRow
          label="Spread"
          value={
            snapshot?.spread_points === null || snapshot?.spread_points === undefined
              ? "—"
              : `${snapshot.spread_points} pts`
          }
          hint={
            snapshot?.spread_price === null || snapshot?.spread_price === undefined
              ? undefined
              : `${snapshot.spread_price}`
          }
        />
        <DataRow label="Volume" value={formatNumber(snapshot?.tick_volume)} hint="source units" />

        <GroupLabel>Session &amp; data</GroupLabel>
        <DataRow
          label="Data state"
          value={snapshot?.data_state ?? "unavailable"}
          toneClassName={
            snapshot?.data_state === "live"
              ? "text-primary"
              : snapshot?.data_state === "stale"
                ? "text-warn"
                : undefined
          }
        />
        <DataRow label="Freshness" value={freshness} />
        <DataRow
          label="Tick lag"
          value={
            snapshot?.tick_lag_seconds === null || snapshot?.tick_lag_seconds === undefined
              ? "—"
              : `${snapshot.tick_lag_seconds.toFixed(1)} s`
          }
        />
        <DataRow label="Bar close" value={formatTimeOnly(barCloseIso)} hint="UTC" />
        <DataRow
          label="Last tick"
          value={formatBrokerTime(snapshot?.tick_time_iso, true)}
          hint="UTC"
        />
        <DataRow
          label="Forecast"
          value={formatTimeOnly(forecast?.created_at)}
          hint="generated"
        />
        <DataRow
          label="Evaluated"
          value={formatTimeOnly(
            evaluatedAt ?? forecast?.evaluation?.at(-1)?.evaluated_at,
          )}
          hint="last step"
        />
        <DataRow
          label="Signal"
          value={formatTimeOnly(signal?.generated_at)}
          hint="calculated"
        />

        <GroupLabel>Technicals</GroupLabel>
        <ReadingRow
          label="EMA structure"
          readingTone={ema.tone}
          primary={ema.label}
          detail={ema.detail}
        />
        <ReadingRow
          label="RSI 14"
          readingTone={rsi.tone}
          primary={formatNumber(latest.rsi14, "—")}
          detail={rsi.label}
        />
        {bb !== null && (
          <div className="border-b border-line-soft/70 px-3 py-[5px]">
            <div className="flex items-center justify-between">
              <span className="text-[10.5px] text-ink-faint">Bollinger position</span>
              <span className="num text-[10.5px] text-ink-muted">{bb.toFixed(0)}%</span>
            </div>
            <div className="mt-1 h-[3px] w-full overflow-hidden rounded-full bg-surface-2">
              <div className="h-full rounded-full bg-primary/50" style={{ width: `${bb}%` }} />
            </div>
          </div>
        )}
        <ReadingRow
          label="MACD 12/26/9"
          readingTone={macd.tone}
          primary={formatNumber(latest.macd, "—")}
          detail={macd.label}
        />
        <ReadingRow
          label="ATR 14"
          readingTone="neutral"
          primary={formatNumber(latest.atr14, "—")}
          detail="volatility"
        />

        <GroupLabel>Signal distribution</GroupLabel>
        <div className="px-2 py-2">
          <SignalDistribution signal={signal} forecast={forecast} compact />
          <Link
            to="/signals"
            className="mt-2 inline-flex items-center gap-1 px-1 text-[10.5px] font-medium text-ink-muted transition-colors hover:text-ink"
          >
            <BrainCircuit className="size-3.5 text-primary" aria-hidden />
            Open signal report
            <ArrowRight className="size-3.5" aria-hidden />
          </Link>
        </div>

        <div className="mx-3 mb-2 rounded-[7px] border border-line-soft bg-surface-2/35 px-2.5 py-2 text-[9.5px] leading-relaxed text-ink-faint">
          Timestamps are normalized to UTC. Volume and candle figures are reported by the active
          market-data provider.
          {status?.last_error && (
            <span className="mt-1 block text-warn/80">{status.last_error}</span>
          )}
        </div>
      </div>
    </aside>
  );
}
