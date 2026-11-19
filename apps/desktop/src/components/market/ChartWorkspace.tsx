import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Crosshair, Layers, Maximize2 } from "lucide-react";

import { PriceChart } from "@/components/market/PriceChart";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { ApiError } from "@/lib/api";
import { DEFAULT_CHART } from "@/lib/defaults";
import { formatBrokerTime } from "@/lib/format";
import type { Candle, CandleSeries, ChartSettings, Indicators } from "@/lib/types";
import { useLiveCandle } from "@/state/live-candles";
import { useMarket } from "@/state/market-context";
import { cn } from "@/lib/utils";

const LAYERS: Array<{ key: keyof ChartSettings; label: string; hint: string }> = [
  { key: "show_ema", label: "EMA 9 / 21 / 50", hint: "overlay" },
  { key: "show_bollinger", label: "Bollinger bands", hint: "overlay" },
  { key: "show_volume", label: "Tick volume", hint: "histogram" },
  { key: "show_rsi", label: "RSI 14", hint: "pane" },
  { key: "show_macd", label: "MACD", hint: "pane" },
  { key: "crosshair", label: "Crosshair magnet", hint: "input" },
];

function LayerMenu({
  chart,
  onToggle,
  disabled,
}: {
  chart: ChartSettings;
  onToggle: (key: keyof ChartSettings) => void;
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <Button
        size="sm"
        variant={open ? "secondary" : "ghost"}
        aria-expanded={open}
        aria-haspopup="menu"
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
        icon={<Layers className="size-3.5" />}
      >
        Layers
      </Button>
      {open && (
        <div
          role="menu"
          aria-label="Chart layers"
          className="glass-veil absolute top-[calc(100%+4px)] right-0 z-30 w-[212px] rounded-[8px] p-1.5"
        >
          <p className="label-xs px-1.5 py-1.5">Chart layers</p>
          {LAYERS.map(({ key, label, hint }) => (
            <button
              key={key}
              type="button"
              role="menuitemcheckbox"
              aria-checked={Boolean(chart[key])}
              onClick={() => onToggle(key)}
              className="flex w-full items-center gap-2 rounded-[5px] px-1.5 py-1.5 text-left transition-colors duration-150 hover:bg-hover"
            >
              <span
                className={cn(
                  "grid size-3.5 shrink-0 place-items-center rounded-[3px] border",
                  chart[key] ? "border-primary/50 bg-primary/15" : "border-line-strong",
                )}
              >
                {chart[key] && <Check className="size-2.5 text-primary" aria-hidden />}
              </span>
              <span className="text-[11px] text-ink-muted">{label}</span>
              <span className="ml-auto text-[9px] text-ink-faint">{hint}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

interface ChartWorkspaceProps {
  candles: CandleSeries | null;
  indicators: Indicators | null;
  loading?: boolean;
  className?: string;
  showFooter?: boolean;
}

/**
 * The primary working surface. No decorative card: a control strip, the chart,
 * and a data-provenance footer.
 */
export function ChartWorkspace({
  candles,
  indicators,
  loading = false,
  className,
  showFooter = true,
}: ChartWorkspaceProps) {
  const { stream, settings, saveSettings } = useMarket();
  const snapshot = stream.snapshot;
  const symbol = settings?.symbol ?? snapshot?.symbol ?? "No symbol";
  const timeframe = settings?.timeframe ?? snapshot?.timeframe ?? "M15";
  const chart = settings?.chart ?? DEFAULT_CHART;
  const digits = snapshot?.digits ?? 2;
  const [fitVersion, setFitVersion] = useState(0);
  const [layerError, setLayerError] = useState<string | null>(null);

  const toggle = async (key: keyof ChartSettings) => {
    try {
      await saveSettings({ chart: { [key]: !chart[key] } });
      setLayerError(null);
    } catch (cause) {
      setLayerError(
        cause instanceof ApiError ? cause.message : "The chart layer could not be saved.",
      );
    }
  };

  const live = useLiveCandle();
  const liveMatches = live?.symbol === symbol && live?.timeframe === timeframe;
  const liveCandle: Candle | null = liveMatches ? live.candle : null;
  const series = useMemo(() => {
    const base = candles?.candles ?? [];
    if (!liveCandle || !live?.closed) return base;
    // The confirmed WebSocket frame can arrive before the reconciliation REST
    // fetch. Merge it by timestamp so the new bar appears immediately.
    const merged = new Map<number, Candle>();
    for (const candle of base) merged.set(candle.time, candle);
    merged.set(liveCandle.time, liveCandle);
    return [...merged.values()].sort((left, right) => left.time - right.time);
  }, [candles?.candles, liveCandle, live?.closed]);
  const forming = liveMatches && live
    ? live.closed
      ? null
      : live.candle
    : (candles?.forming_candle ?? null);
  const state = candles?.data_state ?? snapshot?.data_state ?? "unavailable";
  const source = candles?.source ?? "market";
  const sourceLabel = source === "binance" ? "Binance" : source === "mt5" ? "MetaTrader 5" : source;

  return (
    <section className={cn("flex min-h-0 flex-col bg-chart", className)}>
      <header className="flex h-[34px] shrink-0 items-center gap-2 border-b border-line-soft bg-surface-2/25 px-3">
        <div className="flex min-w-0 items-baseline gap-2">
          <h2 className="num shrink-0 text-[12.5px] font-semibold text-ink">{symbol}</h2>
          <span className="hidden truncate text-[10.5px] text-ink-faint sm:block">
            {snapshot?.symbol_description ?? "Bitcoin vs US Dollar"}
          </span>
        </div>
        <Badge
          tone={state === "live" ? "info" : state === "stale" ? "warning" : "muted"}
          dot
          className="ml-1 hidden md:inline-flex"
        >
          {state}
        </Badge>

        <div className="ml-auto flex shrink-0 items-center gap-1">
          {loading && <Spinner className="mr-1" />}
          {layerError && <span className="mr-1 text-[9px] text-warn">{layerError}</span>}
          <Button
            size="sm"
            variant="ghost"
            aria-label="Fit chart to loaded candles"
            onClick={() => setFitVersion((value) => value + 1)}
            icon={<Maximize2 className="size-3.5" />}
          >
            <span className="hidden lg:inline">Fit</span>
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label="Reset crosshair"
            title={`Crosshair ${chart.crosshair ? "magnet" : "normal"}`}
            onClick={() => void toggle("crosshair")}
            icon={<Crosshair className={cn("size-3.5", chart.crosshair && "text-accent-ink")} />}
          />
          <LayerMenu chart={chart} onToggle={(key) => void toggle(key)} disabled={false} />
        </div>
      </header>

      <div className="min-h-0 flex-1">
        <PriceChart
          candles={series}
          forming={forming}
          indicators={indicators}
          chart={chart}
          digits={digits}
          symbol={symbol}
          timeframe={timeframe}
          source={stream.status?.provider ?? candles?.source ?? "market"}
          fitVersion={fitVersion}
        />
      </div>

      {showFooter && (
        <footer className="flex h-[22px] shrink-0 items-center justify-between gap-3 border-t border-line-soft px-2.5 text-[9px] text-ink-faint">
          <span className="truncate">Source-reported volume · UTC time · read-only</span>
          <span className="num hidden shrink-0 sm:block">
            {candles?.count ?? 0} bars · {sourceLabel} ·{" "}
            {formatBrokerTime(candles?.fetched_at ?? snapshot?.last_update, true)}
          </span>
        </footer>
      )}
    </section>
  );
}
