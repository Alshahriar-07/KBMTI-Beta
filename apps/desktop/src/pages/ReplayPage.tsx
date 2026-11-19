import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Pause, Play, PlayCircle } from "lucide-react";

import { PriceChart } from "@/components/market/PriceChart";
import { AiNotice } from "@/components/ui/AiNotice";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { usePolling } from "@/hooks/usePolling";
import { api } from "@/lib/api";
import { DEFAULT_CHART } from "@/lib/defaults";
import { formatBrokerTime, formatPrice } from "@/lib/format";
import type { ChartSettings, ReplayWindow } from "@/lib/types";
import { useMarket } from "@/state/market-context";
import { cn } from "@/lib/utils";

const WINDOW_SIZE = 160;

const REPLAY_CHART: ChartSettings = {
  ...DEFAULT_CHART,
  show_ema: false,
  show_bollinger: false,
  show_rsi: false,
  show_macd: false,
  show_volume: true,
};

export function ReplayPage() {
  const { stream, settings } = useMarket();
  const symbol = settings?.symbol ?? stream.snapshot?.symbol ?? "";
  const timeframe = settings?.timeframe ?? stream.snapshot?.timeframe ?? "M15";
  const digits = stream.snapshot?.digits ?? 2;
  const [start, setStart] = useState(0);
  const [playing, setPlaying] = useState(false);

  const replay = usePolling<ReplayWindow>(
    `replay:${symbol}:${timeframe}:${start}`,
    () => api.replayWindow(start, WINDOW_SIZE),
    0,
  );

  const total = replay.data?.total ?? 0;
  const maxStart = Math.max(0, total - WINDOW_SIZE);

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      setStart((previous) => {
        if (previous >= maxStart) {
          setPlaying(false);
          return previous;
        }
        return Math.min(previous + 10, maxStart);
      });
    }, 900);
    return () => window.clearInterval(timer);
  }, [playing, maxStart]);

  const candles = replay.data?.candles ?? [];
  const last = candles[candles.length - 1] ?? null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <AiNotice compact className="shrink-0">
        Replay steps through cached candles. Point-in-time PATRON replay is not calculated here;
        stored forecast runs are scored against realised candles on the Forecasts page.
      </AiNotice>

      <section className="flex min-h-0 flex-1 flex-col bg-chart">
        <header className="flex h-[34px] shrink-0 items-center gap-2 border-b border-line-soft bg-surface/60 px-2.5">
          <span className="num text-[11.5px] font-semibold text-ink">{symbol || "No symbol"}</span>
          <span className="text-[9.5px] text-ink-faint">
            {replay.data?.timeframe ?? timeframe} · Replay
          </span>
          <span className="num ml-1 text-[9.5px] text-ink-faint">
            window {replay.data?.start_index ?? 0}–{replay.data?.end_index ?? 0} / {total}
          </span>
          <div className="ml-auto flex items-center gap-1.5">
            <Badge tone="muted">{replay.data?.source ?? "mt5"}</Badge>
            <Badge tone="info">No order execution</Badge>
          </div>
        </header>

        <div className="min-h-0 flex-1">
          {candles.length ? (
            <PriceChart
              candles={candles}
              forming={null}
              indicators={null}
              chart={REPLAY_CHART}
              digits={digits}
              symbol={symbol || "No symbol"}
              timeframe={replay.data?.timeframe ?? timeframe}
            />
          ) : (
            <EmptyState
              icon={PlayCircle}
              title="No cached candles in this window"
              description="Attach MetaTrader 5 and load chart history before replaying."
            />
          )}
        </div>
      </section>

      <section className="shrink-0 border-t border-line bg-surface">
        <div className="flex h-11 items-center gap-2.5 px-3">
          <Button
            size="sm"
            variant="secondary"
            disabled={start <= 0}
            onClick={() => setStart((value) => Math.max(0, value - WINDOW_SIZE))}
            icon={<ChevronLeft className="size-3.5" />}
          >
            Previous
          </Button>
          <Button
            size="sm"
            variant={playing ? "secondary" : "primary"}
            disabled={total === 0}
            onClick={() => setPlaying((value) => !value)}
            icon={playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
          >
            {playing ? "Pause" : "Play 10-bar steps"}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={start >= maxStart}
            onClick={() => setStart((value) => Math.min(maxStart, value + WINDOW_SIZE))}
            icon={<ChevronRight className="size-3.5" />}
          >
            Next
          </Button>

          <div className="ml-auto flex items-center gap-3">
            <span className="hidden text-[9.5px] text-ink-faint md:inline">Timeline</span>
            <input
              type="range"
              min={0}
              max={Math.max(1, maxStart)}
              step={1}
              value={Math.min(start, Math.max(1, maxStart))}
              aria-label="Replay start candle"
              onChange={(event) => setStart(Number(event.target.value))}
              className="h-1 w-[180px] accent-primary disabled:opacity-40"
              disabled={total === 0}
            />
            <span className="num w-[74px] text-right text-[9.5px] text-ink-muted">
              {start} / {maxStart}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-2 divide-x divide-line border-t border-line-soft md:grid-cols-5">
          {[
            { label: "Candles shown", value: `${candles.length}` },
            { label: "Last close", value: formatPrice(last?.close, digits) },
            { label: "Data state", value: replay.data?.data_state ?? "—" },
            { label: "Window end", value: formatBrokerTime(last ? new Date(last.time * 1000).toISOString() : null, true) },
            { label: "Forecast scoring", value: "Forecasts page" },
          ].map((item) => (
            <div key={item.label} className="min-w-0 px-3 py-2">
              <p className="text-[9.5px] font-medium text-ink-faint">{item.label}</p>
              <p
                className={cn(
                  "num mt-0.5 truncate text-[11px] text-ink-muted",
                  item.value === "Forecasts page" && "text-ink-faint",
                )}
              >
                {item.value}
              </p>
            </div>
          ))}
        </div>

        <p className="border-t border-line-soft px-3 py-1.5 text-[9px] leading-relaxed text-ink-faint">
          {replay.data?.message ?? "Replay reads from the local candle cache only."}
        </p>
      </section>
    </div>
  );
}
