import { Play } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { formatPercent, formatPrice, formatTimeOnly } from "@/lib/format";
import type {
  Candle,
  ForecastRun,
  ForecastStatus,
  MarketIntelligence,
  PatronStatus,
} from "@/lib/types";
import { cn } from "@/lib/utils";

function StripHeader({
  title,
  badge,
  meta,
}: {
  title: string;
  badge?: string;
  meta?: string;
}) {
  return (
    <header className="flex h-[26px] shrink-0 items-center gap-2 border-b border-line-soft bg-surface-2/25 px-2.5">
      <h2 className="label-xs truncate">{title}</h2>
      {badge && <Badge tone="info">{badge}</Badge>}
      {meta && <span className="ml-auto truncate text-[9px] text-ink-faint">{meta}</span>}
    </header>
  );
}

function displayState(value?: string | null) {
  if (!value) return "Unavailable";
  const lower = value.toLowerCase();
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}

function displayDevice(value?: string | null) {
  if (!value) return "—";
  const lower = value.toLowerCase();
  if (lower === "cpu") return "CPU";
  if (lower === "cuda") return "CUDA";
  if (lower === "mps") return "MPS";
  return value;
}

function MiniStat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[8.5px] text-ink-faint">{label}</p>
      <p className={cn("num mt-0.5 truncate text-[10.5px] text-ink-muted", tone)}>{value}</p>
    </div>
  );
}

/**
 * Miniature forecast preview for the existing PATRON strip.
 *
 * Uses the OHLC candles persisted with the latest PATRON run. When the active
 * chart is Binance BTC/USDT 15m, the real forming candle is drawn alongside the
 * six predictions; otherwise only genuine predicted candles are shown.
 */
function MiniForecastCandles({
  current,
  latest,
}: {
  current: Candle | null;
  latest: ForecastRun | null;
}) {
  const anchor = current?.time ?? latest?.input_last_bar_at ?? null;
  const steps = [...(latest?.candles ?? [])]
    .filter((step) => anchor === null || step.timestamp_utc > anchor)
    .sort((a, b) => a.sequence - b.sequence)
    .slice(0, 6);

  if (!steps.length) {
    return (
      <div className="forecast-enter flex h-[78px] w-[52%] min-w-[180px] max-w-[280px] shrink-0 items-center justify-center rounded-[7px] border border-dashed border-line-soft px-2 text-center text-[8.5px] leading-snug text-ink-faint">
        {latest?.candles?.length
          ? "No active predictions · waiting for the next close"
          : "Waiting for a stored PATRON forecast"}
      </div>
    );
  }

  const candles = current
    ? [
        { candle: current, predicted: false },
        ...steps.map((step) => ({ candle: step, predicted: true })),
      ]
    : steps.map((step) => ({ candle: step, predicted: true }));
  const values = candles.flatMap(({ candle }) => [candle.high, candle.low]);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || Math.max(1, max * 0.001);
  const width = 238;
  const height = 74;
  const innerTop = 6;
  const innerBottom = 68;
  const slot = width / candles.length;
  const body = Math.max(6, Math.min(13, slot * 0.48));
  const y = (value: number) =>
    innerTop + (1 - (value - (min - span * 0.06)) / (span * 1.12)) * (innerBottom - innerTop);
  const reference = latest?.output?.meta?.reference_close ?? null;

  return (
    <div className="forecast-enter w-[52%] min-w-[180px] max-w-[280px] shrink-0">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[8.5px] font-medium text-ink-faint">Next {steps.length}</span>
        <span className="text-[8.5px] font-medium text-primary">PATRON</span>
      </div>
      <div className="mt-0.5 flex items-stretch gap-1.5">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={`Preview of the current candle and ${steps.length} PATRON predicted candles`}
          className="h-[74px] min-w-0 flex-1 overflow-visible"
        >
          <rect
            x={current ? slot : 0}
            y="0"
            width={current ? width - slot : width}
            height={height}
            fill="var(--color-primary)"
            fillOpacity="0.035"
          />
          {[0.25, 0.5, 0.75].map((fraction) => (
            <line
              key={fraction}
              x1="0"
              x2={width}
              y1={innerTop + (innerBottom - innerTop) * fraction}
              y2={innerTop + (innerBottom - innerTop) * fraction}
              stroke="var(--color-line-soft)"
              strokeOpacity="0.7"
              strokeWidth="0.7"
            />
          ))}
          {reference !== null && (
            <line
              x1="0"
              x2={width}
              y1={y(reference)}
              y2={y(reference)}
              stroke="var(--color-primary)"
              strokeOpacity="0.5"
              strokeDasharray="3 2"
              strokeWidth="0.9"
            />
          )}
          {current && (
            <line
              x1={slot}
              x2={slot}
              y1={innerTop}
              y2={innerBottom}
              stroke="var(--color-primary)"
              strokeOpacity="0.55"
              strokeDasharray="2 2"
              strokeWidth="0.9"
            />
          )}
          {candles.map(({ candle, predicted }, index) => {
            const center = slot * (index + 0.5);
            const bull = candle.close >= candle.open;
            const color = bull ? "var(--color-bull)" : "var(--color-bear)";
            const top = Math.min(y(candle.open), y(candle.close));
            const bodyHeight = Math.max(2, Math.abs(y(candle.open) - y(candle.close)));
            return (
              <g key={`${predicted ? "p" : "a"}-${index}`}>
                <title>
                  {predicted
                    ? `Predicted candle ${index + (current ? 0 : 1)} · close ${formatPrice(candle.close, 2)}`
                    : `Current candle · close ${formatPrice(candle.close, 2)}`}
                </title>
                <line
                  x1={center}
                  x2={center}
                  y1={y(candle.high)}
                  y2={y(candle.low)}
                  stroke={color}
                  strokeOpacity={predicted ? 0.85 : 1}
                  strokeWidth="1.2"
                  strokeDasharray={predicted ? "2 1.4" : undefined}
                />
                <rect
                  x={center - body / 2}
                  y={top}
                  width={body}
                  height={bodyHeight}
                  rx="0.6"
                  fill={color}
                  fillOpacity={predicted ? 0.32 : 0.96}
                  stroke={color}
                  strokeOpacity={predicted ? 0.95 : 0}
                  strokeWidth="0.9"
                />
              </g>
            );
          })}
        </svg>
        <div className="flex w-[38px] shrink-0 flex-col justify-between py-[1px] text-right text-[7.5px] leading-none text-ink-faint">
          <span className="num">{formatPrice(max, 2)}</span>
          {reference !== null && (
            <span className="num text-primary/80">{formatPrice(reference, 2)}</span>
          )}
          <span className="num">{formatPrice(min, 2)}</span>
        </div>
      </div>
      <div className="mt-0.5 flex items-center justify-between gap-2 text-[7.5px] text-ink-faint">
        <span>{current ? "Now · actual" : "Last close"}</span>
        <span>{steps.length} × 15m</span>
      </div>
    </div>
  );
}

export function BottomIntelligence({
  forecast,
  latest,
  patron,
  running,
  onRun,
  currentCandle = null,
  intelligence = null,
  intelligenceLoading = false,
  intelligenceError = null,
}: {
  forecast: ForecastStatus | null;
  latest: ForecastRun | null;
  patron: PatronStatus | null;
  running: boolean;
  onRun: () => void;
  currentCandle?: Candle | null;
  intelligence?: MarketIntelligence | null;
  intelligenceLoading?: boolean;
  intelligenceError?: string | null;
}) {
  const ready = Boolean(patron?.ready || forecast?.ai_available);
  const output = latest?.output?.patron ?? null;
  const reference = latest?.output?.meta?.reference_close ?? null;
  const step = output?.range_quantiles?.[output.range_quantiles.length - 1];
  const median = reference !== null && step ? reference * (1 + step.close.q50) : null;
  const low = reference !== null && step ? reference * (1 + step.close.q10) : null;
  const high = reference !== null && step ? reference * (1 + step.close.q90) : null;
  const change = reference && median ? ((median - reference) / reference) * 100 : null;
  const barrier = output?.barrier_probabilities;
  const confirmedBarIso = latest?.input_last_bar_at
    ? new Date(latest.input_last_bar_at * 1000).toISOString()
    : null;

  return (
    <section className="grid h-full grid-cols-1 divide-y divide-line border-t border-line bg-surface md:grid-cols-2 md:divide-x md:divide-y-0">
      <section className="flex min-h-0 flex-col">
        <StripHeader
          title="PATRON source evidence"
          badge="SOURCE"
          meta={
            intelligence
              ? `Assessment ${intelligence.forecast_assessment.status}`
              : latest?.created_at
                ? `Generated ${formatTimeOnly(latest.created_at, false)}`
                : output
                  ? `As of ${formatTimeOnly(output.as_of)}`
                  : "No run"
          }
        />
        <div className="flex min-h-0 flex-1 flex-col px-2.5 py-1.5">
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              {output && median !== null && reference !== null ? (
                <>
                  <div className="flex items-baseline gap-2">
                    <span className="num text-[18px] leading-none text-ink">
                      {formatPrice(median, 2)}
                    </span>
                    <span
                      className={cn(
                        "num text-[10px]",
                        (change ?? 0) > 0
                          ? "text-bull"
                          : (change ?? 0) < 0
                            ? "text-bear"
                            : "text-ink-muted",
                      )}
                    >
                      {formatPercent(change, 3)}
                    </span>
                  </div>
                  <p className="mt-1 truncate text-[9px] text-ink-faint">
                    80% band {formatPrice(low, 2)} – {formatPrice(high, 2)}
                  </p>
                  <p className="mt-0.5 truncate text-[9px] text-ink-faint">
                    Bar {formatTimeOnly(confirmedBarIso, false)} · Ref. {formatPrice(reference, 2)} ·{" "}
                    {barrier
                      ? `Barrier ${Object.entries(barrier).sort((a, b) => b[1] - a[1])[0][0].replace("_", " ")}`
                      : "No barrier"}
                  </p>
                </>
              ) : (
                <>
                  <div className="flex items-baseline gap-2">
                    <span className="num text-[18px] leading-none text-ink-faint/70">—</span>
                    <span className="text-[9px] text-ink-faint">
                      {ready ? "No forecast run" : "Model not ready"}
                    </span>
                  </div>
                  <p className="mt-1 line-clamp-2 max-w-[230px] text-[9px] leading-relaxed text-ink-faint">
                    {ready
                      ? "PATRON is loaded. Run a forecast to persist the model's predicted candles."
                      : (forecast?.message ??
                        "No PATRON forecast. No synthetic estimate is shown.")}
                  </p>
                </>
              )}
            </div>
            <MiniForecastCandles
              key={latest?.id ?? "no-run"}
              current={currentCandle}
              latest={latest}
            />
          </div>
          <div className="mt-auto flex items-end justify-between gap-3 pt-1">
            <div className="grid grid-cols-3 gap-3">
              <MiniStat label="Horizon" value={`${output?.horizon_minutes ?? 90} min`} />
              <MiniStat
                label="Next"
                value={latest?.candles?.length ? `${latest.candles.length} candles` : "—"}
              />
              <MiniStat label="Latency" value={latest?.latency_ms ? `${latest.latency_ms.toFixed(0)} ms` : "—"} />
            </div>
            <Button
              size="sm"
              variant="primary"
              disabled={!ready || running}
              onClick={onRun}
              icon={running ? <Spinner /> : <Play className="size-3" />}
            >
              {running ? "Running" : "Run"}
            </Button>
          </div>
        </div>
      </section>

      <section className="flex min-h-0 flex-col">
        <StripHeader
          title="AI market view"
          badge={intelligence?.ai_status.used ? "QWEN" : "DETERMINISTIC"}
          meta={
            intelligence
              ? intelligence.ai_status.status
              : intelligenceLoading
                ? "Loading"
                : "Unavailable"
          }
        />
        <div className="flex min-h-0 flex-1 flex-col px-2.5 py-2">
          {intelligence ? (
            <>
              <div className="flex items-center gap-2">
                <Badge
                  tone={
                    intelligence.decision === "LONG"
                      ? "success"
                      : intelligence.decision === "SHORT"
                        ? "danger"
                        : "warning"
                  }
                  dot
                >
                  {intelligence.decision}
                </Badge>
                <span className="text-[9px] text-ink-faint">
                  Forecast {intelligence.forecast_assessment.status.replaceAll("_", " ")}
                </span>
              </div>
              <p className="mt-1.5 line-clamp-2 text-[9px] leading-relaxed text-ink-muted">
                {intelligence.ai_market_interpretation}
              </p>
              <p className="mt-1 line-clamp-1 text-[8.5px] text-ink-faint">
                {intelligence.ai_forecast_interpretation}
              </p>
              <div className="mt-auto grid grid-cols-2 gap-x-4 gap-y-1 pt-1.5">
                <MiniStat
                  label="Forecast evidence"
                  value={
                    intelligence.forecast_assessment.usable_in_decision
                      ? "Usable"
                      : "Excluded"
                  }
                  tone={
                    intelligence.forecast_assessment.usable_in_decision
                      ? "text-bull"
                      : "text-warn"
                  }
                />
                <MiniStat label="AI state" value={intelligence.ai_status.status} />
                <MiniStat
                  label="PATRON"
                  value={intelligence.forecast_source?.model_version ?? "unavailable"}
                />
                <MiniStat label="Execution" value={intelligence.execution} />
              </div>
            </>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col justify-center">
              <p className="text-[9.5px] leading-relaxed text-ink-faint">
                {intelligenceLoading
                  ? "Building the unified market and PATRON assessment…"
                  : intelligenceError
                    ? `AI analysis unavailable: ${intelligenceError}`
                    : "AI analysis unavailable. Deterministic market data and risk checks remain; no raw PATRON output is shown as a final decision."}
              </p>
              <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1">
                <MiniStat label="Model" value={forecast?.model_id ?? "patron-1.0.0"} />
                <MiniStat
                  label="PATRON state"
                  value={displayState(patron?.state ?? forecast?.state)}
                  tone={ready ? "text-bull" : "text-warn"}
                />
                <MiniStat label="Device" value={displayDevice(patron?.device ?? forecast?.device)} />
                <MiniStat
                  label="Inference"
                  value={`${patron?.inference_count ?? 0} runs`}
                />
              </div>
            </div>
          )}
        </div>
      </section>

    </section>
  );
}
