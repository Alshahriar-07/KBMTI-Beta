import { useMemo } from "react";
import { Activity, ChevronDown } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { formatTimeOnly } from "@/lib/format";
import {
  buildSignalDistribution,
  type SignalDistributionData,
} from "@/lib/signal-distribution";
import type { ForecastRun, Signal } from "@/lib/types";
import { cn } from "@/lib/utils";

const MOMENTUM_LABELS: Record<string, string> = {
  strong_bullish: "Strong bullish",
  bullish: "Bullish",
  sideways: "Sideways",
  neutral: "Sideways",
  bearish: "Bearish",
  strong_bearish: "Strong bearish",
};

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[9px] text-ink-faint">{label}</dt>
      <dd className="num mt-0.5 truncate text-[9.5px] text-ink-muted" title={value}>
        {value}
      </dd>
    </div>
  );
}

function SignalDetails({ data }: { data: SignalDistributionData }) {
  const classes = data.classProbabilities
    ? Object.entries(data.classProbabilities).sort((a, b) => b[1] - a[1])
    : [];
  return (
    <details className="group mt-2 border-t border-line-soft pt-1.5">
      <summary className="flex cursor-pointer list-none items-center gap-1 text-[9.5px] font-medium text-ink-faint transition-colors hover:text-ink-muted">
        <ChevronDown className="size-3 transition-transform group-open:rotate-180" />
        Signal details
      </summary>
      <dl className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-1.5">
        <Detail label="Source" value={data.sourceLabel} />
        <Detail label="Freshness" value={data.freshnessLabel} />
        {data.ruleScore !== null && (
          <Detail label="Raw score" value={data.ruleScore.toFixed(2)} />
        )}
        {data.ruleLabel && <Detail label="Rule label" value={data.ruleLabel} />}
        {data.engine && <Detail label="Engine" value={data.engine} />}
        {data.sourceBars !== null && (
          <Detail label="Source bars" value={String(data.sourceBars)} />
        )}
        {data.modelId && <Detail label="Model" value={data.modelId} />}
        {data.forecastId && <Detail label="Forecast run" value={data.forecastId.slice(0, 10)} />}
      </dl>

      {classes.length > 0 && (
        <div className="mt-2">
          <p className="text-[9px] text-ink-faint">Momentum classes</p>
          <div className="mt-1 space-y-0.5">
            {classes.map(([key, value]) => (
              <div key={key} className="flex items-center justify-between gap-2">
                <span className="truncate text-[9.5px] text-ink-faint">
                  {MOMENTUM_LABELS[key] ?? key}
                </span>
                <span className="num text-[9.5px] text-ink-muted">
                  {(value * 100).toFixed(1)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {data.barrierProbabilities && (
        <div className="mt-2">
          <p className="text-[9px] text-ink-faint">Barrier probabilities</p>
          <div className="mt-1 flex items-center justify-between gap-2 text-[9.5px] text-ink-faint">
            <span>TP first {(data.barrierProbabilities.tp_first * 100).toFixed(1)}%</span>
            <span>SL first {(data.barrierProbabilities.sl_first * 100).toFixed(1)}%</span>
            <span>Timeout {(data.barrierProbabilities.timeout * 100).toFixed(1)}%</span>
          </div>
        </div>
      )}

      <p className="mt-2 text-[9.5px] leading-relaxed text-ink-faint">{data.derivation}</p>
      {data.aiNote && (
        <p className="mt-1 text-[9.5px] leading-relaxed text-ink-faint">{data.aiNote}</p>
      )}
    </details>
  );
}

export function SignalDistribution({
  signal,
  forecast,
  compact = false,
  className,
}: {
  signal: Signal | null;
  forecast: ForecastRun | null;
  compact?: boolean;
  className?: string;
}) {
  const data = useMemo(() => buildSignalDistribution(signal, forecast), [signal, forecast]);

  if (!data) {
    return (
      <div
        className={cn(
          "rounded-[10px] border border-line-soft bg-surface px-3 py-3",
          className,
        )}
      >
        <div className="flex items-center gap-2 text-[11px] font-medium text-ink-muted">
          <Activity className="size-3.5 text-ink-faint" aria-hidden />
          Signal unavailable
        </div>
        <p className="mt-1 text-[10px] leading-relaxed text-ink-faint">
          No fresh PATRON forecast or rule-based reading is available. The BUY/SELL split is
          withheld rather than fabricated.
        </p>
      </div>
    );
  }

  const barHeight = compact ? "h-[64px]" : "h-[86px]";
  const largeNumberSize = compact ? "text-[20px]" : "text-[34px]";

  const section = (share: number, label: string, tone: "bull" | "bear") => {
    const isBull = tone === "bull";
    const numberSize =
      share >= 25
        ? largeNumberSize
        : share >= 16
          ? compact
            ? "text-[13px]"
            : "text-[15px]"
          : share >= 8
            ? "text-[9px]"
            : "text-[8px]";
    return (
      <div
        className={cn(
          "flex min-w-0 flex-col items-center justify-center overflow-hidden transition-[width] duration-500 ease-out",
          isBull ? "bg-bull/15" : "bg-bear/15",
        )}
        style={{ width: `${share}%` }}
      >
        {share >= 6 && (
          <span
            className={cn(
              "num leading-none font-semibold whitespace-nowrap",
              isBull ? "text-bull" : "text-bear",
              numberSize,
            )}
          >
            {share.toFixed(1)}%
          </span>
        )}
        {share >= 16 && (
          <span
            className={cn(
              "mt-1 text-[9px] font-medium tracking-[0.12em] whitespace-nowrap",
              isBull ? "text-bull/80" : "text-bear/80",
            )}
          >
            {label}
          </span>
        )}
      </div>
    );
  };

  return (
    <div
      className={cn(
        "rounded-[10px] border border-line-soft bg-surface px-3 py-2.5",
        compact && "px-2 py-2",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2">
        {compact ? (
          <span className="text-[9px] font-medium text-ink-faint">{data.sourceLabel}</span>
        ) : (
          <h3 className="text-[11.5px] font-semibold text-ink">{data.title}</h3>
        )}
        <Badge tone={data.fresh ? "success" : "warning"} dot>
          {data.fresh ? "Live" : "Stale"}
        </Badge>
      </div>

      <div
        role="img"
        aria-label={`BUY ${data.buy.toFixed(1)} percent, SELL ${data.sell.toFixed(1)} percent. ${data.interpretation}`}
        className={cn(
          "mt-2 flex w-full gap-[2px] overflow-hidden rounded-[6px] bg-app",
          barHeight,
          !data.fresh && "opacity-75",
        )}
      >
        {section(data.buy, "BUY", "bull")}
        {section(data.sell, "SELL", "bear")}
      </div>

      {(data.buy < 16 || data.sell < 16) && (
        <p className="num mt-1 text-center text-[9px] text-ink-faint">
          BUY {data.buy.toFixed(1)}% · SELL {data.sell.toFixed(1)}%
        </p>
      )}

      <p
        className={cn(
          "mt-2 leading-relaxed text-ink-muted",
          compact ? "text-[10px]" : "text-[11px]",
        )}
      >
        {data.interpretation}
      </p>

      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[9px] text-ink-faint">
        <span>{data.strengthLabel} signal</span>
        {data.confidence !== null && (
          <span className="num">top class {data.confidence.toFixed(0)}%</span>
        )}
        <span className="num ml-auto">
          {data.updatedAt ? `Updated ${formatTimeOnly(data.updatedAt)} UTC` : "no timestamp"}
        </span>
      </div>

      <SignalDetails data={data} />
    </div>
  );
}
