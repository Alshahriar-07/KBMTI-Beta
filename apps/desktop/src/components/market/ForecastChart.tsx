import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";

import { formatPrice } from "@/lib/format";
import type { Candle, ForecastRun } from "@/lib/types";
import { cn } from "@/lib/utils";

const HISTORY_WINDOW = 56;
const PAD = { top: 18, right: 76, bottom: 28, left: 10 };
const BULL = "var(--color-bull)";
const BEAR = "var(--color-bear)";

type PredictedCandle = NonNullable<ForecastRun["candles"]>[number];

interface Slot {
  kind: "actual" | "forming" | "predicted";
  candle: Candle;
  time: number;
  predicted?: PredictedCandle;
}

function hhmm(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toISOString().slice(11, 16);
}

/**
 * Actual closed candles, the forming candle and PATRON's stored future candles
 * on one shared price scale. Predicted candles are outlined and translucent so
 * they can never be mistaken for confirmed market data; no candle is drawn
 * unless it came from Binance or the persisted PATRON payload.
 */
export function ForecastChart({
  history,
  forming,
  run,
  digits = 2,
}: {
  history: Candle[];
  forming: Candle | null;
  run: ForecastRun | null;
  digits?: number;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 960, height: 440 });
  const [hover, setHover] = useState<{ index: number; x: number; y: number } | null>(null);

  useEffect(() => {
    const element = wrapRef.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (!rect) return;
      setSize({
        width: Math.max(320, Math.round(rect.width)),
        height: Math.max(280, Math.round(rect.height)),
      });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const geometry = useMemo(() => {
    const bars = history.slice(-HISTORY_WINDOW);
    const predictions = [...(run?.candles ?? [])].sort(
      (a, b) => a.timestamp_utc - b.timestamp_utc,
    );
    const lastClosed = bars.length ? bars[bars.length - 1] : null;
    const anchor = forming?.time ?? (lastClosed ? lastClosed.time + 900 : null);

    // Only predictions that are still at or ahead of the current bar belong on
    // the forward region. Stale targets have already closed and are shown as
    // actual candles / in the evaluation timeline instead.
    const active = anchor === null ? [] : predictions.filter((step) => step.timestamp_utc >= anchor);
    const overlapping = forming
      ? active.filter((step) => step.timestamp_utc === forming.time)
      : [];
    const forward = active.filter((step) =>
      forming ? step.timestamp_utc > forming.time : step.timestamp_utc > (lastClosed?.time ?? 0),
    );

    const slots: Slot[] = bars.map((candle) => ({
      kind: "actual" as const,
      candle,
      time: candle.time,
    }));
    const lastActualIndex = slots.length - 1;
    if (forming) {
      slots.push({
        kind: "forming",
        candle: forming,
        time: forming.time,
        predicted: overlapping[0],
      });
    }
    for (const step of forward) {
      slots.push({
        kind: "predicted",
        candle: {
          time: step.timestamp_utc,
          open: step.open,
          high: step.high,
          low: step.low,
          close: step.close,
          tick_volume: 0,
          spread: 0,
          real_volume: 0,
          source: "patron",
          symbol: "BTCUSDT",
        },
        time: step.timestamp_utc,
        predicted: step,
      });
    }

    const prices = [
      ...bars.flatMap((candle) => [candle.high, candle.low]),
      ...(forming ? [forming.high, forming.low] : []),
      ...active.flatMap((step) => [step.high, step.low]),
      ...(run?.output?.meta?.reference_close ? [run.output.meta.reference_close] : []),
    ];
    if (!prices.length) return null;
    let min = Math.min(...prices);
    let max = Math.max(...prices);
    if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) {
      min -= 0.5;
      max += 0.5;
    }
    const padding = (max - min) * 0.06;
    min -= padding;
    max += padding;

    const innerW = size.width - PAD.left - PAD.right;
    const innerH = size.height - PAD.top - PAD.bottom;
    const slotW = innerW / Math.max(1, slots.length);
    const bodyW = Math.max(2, Math.min(14, slotW * 0.62));
    const x = (index: number) => PAD.left + slotW * (index + 0.5);
    const y = (value: number) => PAD.top + (1 - (value - min) / (max - min)) * innerH;

    const grid = [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({
      y: PAD.top + ratio * innerH,
      value: max - ratio * (max - min),
    }));

    const boundaryX =
      lastActualIndex >= 0 ? x(lastActualIndex) + slotW / 2 : PAD.left;
    const firstForecastIndex = forming ? lastActualIndex + 1 : lastActualIndex + 1;
    const lastSlot = slots[slots.length - 1];
    const currentPrice = forming?.close ?? lastClosed?.close ?? null;

    return {
      slots,
      active,
      lastClosed,
      anchor,
      grid,
      x,
      y,
      slotW,
      bodyW,
      boundaryX,
      firstForecastIndex,
      lastClosedIndex: lastActualIndex,
      lastTime: lastSlot?.time ?? null,
      firstTime: slots[0]?.time ?? null,
      currentPrice,
      innerRight: size.width - PAD.right,
      innerTop: PAD.top,
      innerBottom: size.height - PAD.bottom,
    };
  }, [history, forming, run, size.width, size.height]);

  if (!geometry) {
    return (
      <div className="flex h-full min-h-[280px] items-center justify-center border border-dashed border-line bg-chart">
        <p className="max-w-[360px] px-6 text-center text-[11px] leading-relaxed text-ink-faint">
          Waiting for closed Binance BTC/USDT 15m candles. Nothing is drawn until real
          market data arrives.
        </p>
      </div>
    );
  }

  const {
    slots,
    active,
    grid,
    x,
    y,
    bodyW,
    boundaryX,
    firstForecastIndex,
    lastClosedIndex,
    lastTime,
    firstTime,
    currentPrice,
    innerRight,
    innerTop,
    innerBottom,
  } = geometry;
  const firstPredicted = slots.find((slot) => slot.predicted);
  const predictionsTotal = active.length;
  const hovered = hover ? slots[hover.index] : null;

  const handleMove = (event: ReactMouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    if (x < PAD.left || x > innerRight || y < PAD.top || y > innerBottom) {
      setHover(null);
      return;
    }
    const index = Math.max(
      0,
      Math.min(slots.length - 1, Math.floor((x - PAD.left) / geometry.slotW)),
    );
    setHover({ index, x, y });
  };

  return (
    <div ref={wrapRef} className="relative h-full min-h-[280px] w-full">
      <svg
        width={size.width}
        height={size.height}
        role="img"
        aria-label="BTC/USDT 15m candlestick chart with the forming candle and PATRON predicted candles"
        className="block cursor-crosshair"
        onMouseMove={handleMove}
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <pattern id="forecast-hatch" width="6" height="6" patternUnits="userSpaceOnUse">
            <path d="M0 6 L6 0" stroke="var(--color-primary)" strokeOpacity="0.04" strokeWidth="1" />
          </pattern>
        </defs>

        <rect
          x={boundaryX}
          y={PAD.top}
          width={Math.max(0, innerRight - boundaryX)}
          height={innerBottom - innerTop}
          fill="url(#forecast-hatch)"
        />

        {grid.map((line) => (
          <g key={`grid-${line.y}`}>
            <line
              x1={PAD.left}
              x2={innerRight}
              y1={line.y}
              y2={line.y}
              className="stroke-line-soft"
              strokeWidth="1"
            />
            <text
              x={innerRight + 7}
              y={line.y + 3}
              className="num fill-ink-faint text-[9.5px]"
            >
              {formatPrice(line.value, digits)}
            </text>
          </g>
        ))}

        <line
          x1={boundaryX}
          x2={boundaryX}
          y1={PAD.top}
          y2={innerBottom}
          className="stroke-primary/45"
          strokeWidth="1"
          strokeDasharray="3 3"
        />
        <text
          x={boundaryX + 5}
          y={PAD.top - 6}
          className="fill-primary/75 text-[8.5px] tracking-[0.04em]"
        >
          Forecast
        </text>

        {slots.map((slot, index) => {
          const { candle } = slot;
          const isPredicted = slot.kind === "predicted";
          const isForming = slot.kind === "forming";
          const predicted = slot.predicted;
          const bull = candle.close >= candle.open;
          const color = bull ? BULL : BEAR;
          const center = x(index);
          const bodyTop = Math.min(y(candle.open), y(candle.close));
          const bodyHeight = Math.max(1, Math.abs(y(candle.open) - y(candle.close)));
          // The forming bar shares its slot with PATRON's step-1 prediction so
          // the in-progress target is visible without pretending it is future.
          const halfWidth = isForming && predicted ? bodyW * 0.34 : bodyW * 0.5;
          const offset = isForming && predicted ? bodyW * 0.36 : 0;
          const title = `${isPredicted ? "Predicted" : isForming ? "Forming" : ""} ${hhmm(candle.time)} UTC · O ${formatPrice(candle.open, digits)} H ${formatPrice(candle.high, digits)} L ${formatPrice(candle.low, digits)} C ${formatPrice(candle.close, digits)}`;
          return (
            <g key={`${slot.kind}-${slot.time}-${index}`}>
              <title>{title}</title>
              {isPredicted ? (
                <>
                  <line
                    x1={center}
                    x2={center}
                    y1={y(candle.high)}
                    y2={y(candle.low)}
                    stroke={color}
                    strokeOpacity="0.75"
                    strokeWidth="1"
                    strokeDasharray="2 2"
                  />
                  <rect
                    x={center - halfWidth}
                    y={bodyTop}
                    width={halfWidth * 2}
                    height={bodyHeight}
                    fill={color}
                    fillOpacity="0.18"
                    stroke={color}
                    strokeOpacity="0.9"
                    strokeWidth="1"
                    strokeDasharray="3 2"
                  />
                  <text
                    x={center}
                    y={innerBottom + 11}
                    textAnchor="middle"
                    className="fill-primary/75 text-[8.5px]"
                  >
                    P{slot.predicted?.sequence !== undefined ? slot.predicted.sequence + 1 : ""}
                  </text>
                </>
              ) : isForming ? (
                <>
                  <line
                    x1={center - offset}
                    x2={center - offset}
                    y1={y(candle.high)}
                    y2={y(candle.low)}
                    stroke={color}
                    strokeWidth="1"
                  />
                  <rect
                    x={center - offset - halfWidth}
                    y={bodyTop}
                    width={halfWidth * 2}
                    height={bodyHeight}
                    fill={color}
                    fillOpacity="0.85"
                    stroke="var(--color-ink)"
                    strokeOpacity="0.65"
                    strokeWidth="1"
                  />
                  <text
                    x={center - offset}
                    y={innerBottom + 11}
                    textAnchor="middle"
                    className="fill-ink-muted text-[8.5px]"
                  >
                    NOW
                  </text>
                  {predicted && (
                    <>
                      <line
                        x1={center + offset}
                        x2={center + offset}
                        y1={y(predicted.high)}
                        y2={y(predicted.low)}
                        stroke={predicted.close >= predicted.open ? BULL : BEAR}
                        strokeOpacity="0.75"
                        strokeWidth="1"
                        strokeDasharray="2 2"
                      />
                      <rect
                        x={center + offset - halfWidth}
                        y={Math.min(y(predicted.open), y(predicted.close))}
                        width={halfWidth * 2}
                        height={Math.max(1, Math.abs(y(predicted.open) - y(predicted.close)))}
                        fill={predicted.close >= predicted.open ? BULL : BEAR}
                        fillOpacity="0.18"
                        stroke={predicted.close >= predicted.open ? BULL : BEAR}
                        strokeOpacity="0.9"
                        strokeWidth="1"
                        strokeDasharray="3 2"
                      />
                      <text
                        x={center + offset}
                        y={innerBottom + 22}
                        textAnchor="middle"
                        className="fill-primary/75 text-[8.5px]"
                      >
                        P1
                      </text>
                    </>
                  )}
                </>
              ) : (
                <>
                  <line
                    x1={center}
                    x2={center}
                    y1={y(candle.high)}
                    y2={y(candle.low)}
                    stroke={color}
                    strokeWidth="1"
                  />
                  <rect
                    x={center - halfWidth}
                    y={bodyTop}
                    width={halfWidth * 2}
                    height={bodyHeight}
                    fill={color}
                    fillOpacity="0.92"
                  />
                </>
              )}
            </g>
          );
        })}

        {firstPredicted?.predicted && geometry.lastClosed && lastClosedIndex >= 0 && (
          <line
            x1={x(lastClosedIndex)}
            y1={y(geometry.lastClosed.close)}
            x2={x(firstForecastIndex)}
            y2={y(firstPredicted.predicted.open)}
            className="stroke-primary/45"
            strokeWidth="1"
            strokeDasharray="4 3"
          />
        )}

        {hover && hovered && (
          <g pointerEvents="none">
            <line
              x1={x(hover.index)}
              x2={x(hover.index)}
              y1={PAD.top}
              y2={innerBottom}
              stroke="var(--color-ink-faint)"
              strokeOpacity="0.55"
              strokeWidth="1"
              strokeDasharray="2 3"
            />
            <line
              x1={PAD.left}
              x2={innerRight}
              y1={hover.y}
              y2={hover.y}
              stroke="var(--color-ink-faint)"
              strokeOpacity="0.35"
              strokeWidth="1"
              strokeDasharray="2 4"
            />
          </g>
        )}

        {currentPrice !== null && (
          <>
            <line
              x1={PAD.left}
              x2={innerRight}
              y1={y(currentPrice)}
              y2={y(currentPrice)}
              className="stroke-ink/25"
              strokeWidth="1"
              strokeDasharray="1 4"
            />
            <rect
              x={innerRight + 2}
              y={y(currentPrice) - 7}
              width={PAD.right - 6}
              height={14}
              className="fill-primary"
            />
            <text
              x={innerRight + 6}
              y={y(currentPrice) + 3.5}
              className="num fill-white text-[9.5px]"
            >
              {formatPrice(currentPrice, digits)}
            </text>
          </>
        )}

        {firstTime !== null && (
          <text x={PAD.left} y={size.height - 6} className="num fill-ink-faint text-[9px]">
            {hhmm(firstTime)} UTC
          </text>
        )}
        {lastTime !== null && (
          <text
            x={innerRight}
            y={size.height - 6}
            textAnchor="end"
            className="num fill-ink-faint text-[9px]"
          >
            {hhmm(lastTime)} UTC
          </text>
        )}
        {geometry.anchor !== null && (
          <text
            x={(boundaryX + innerRight) / 2}
            y={size.height - 6}
            textAnchor="middle"
            className="fill-primary/70 text-[9px] tracking-[0.02em]"
          >
            PATRON · {predictionsTotal} predicted candle{predictionsTotal === 1 ? "" : "s"}
          </text>
        )}
      </svg>

      {hover && hovered && (
        <div
          className="pointer-events-none absolute z-20 w-[172px] rounded-[8px] border border-line bg-surface px-2.5 py-2 shadow-[0_8px_22px_-16px_rgba(0,0,0,0.7)]"
          style={{
            left: Math.max(
              4,
              Math.min(
                hover.x + 12 + 172 > size.width ? hover.x - 172 - 12 : hover.x + 12,
                size.width - 176,
              ),
            ),
            top: Math.max(4, Math.min(hover.y - 28, size.height - 118)),
          }}
        >
          <div className="flex items-center justify-between gap-2">
            <span
              className={cn(
                "text-[9px] font-medium",
                hovered.kind === "predicted" ? "text-primary" : "text-ink-faint",
              )}
            >
              {hovered.kind === "predicted"
                ? `PATRON P${(hovered.predicted?.sequence ?? 0) + 1}`
                : hovered.kind === "forming"
                  ? "Forming candle"
                  : "Actual candle"}
            </span>
            <span className="num text-[9px] text-ink-faint">{hhmm(hovered.time)} UTC</span>
          </div>
          <div className="mt-1 grid grid-cols-2 gap-x-2 gap-y-[1px] text-[9.5px]">
            <span className="text-ink-faint">O</span>
            <span className="num text-right text-ink-muted">
              {formatPrice(hovered.candle.open, digits)}
            </span>
            <span className="text-ink-faint">H</span>
            <span className="num text-right text-ink-muted">
              {formatPrice(hovered.candle.high, digits)}
            </span>
            <span className="text-ink-faint">L</span>
            <span className="num text-right text-ink-muted">
              {formatPrice(hovered.candle.low, digits)}
            </span>
            <span className="text-ink-faint">C</span>
            <span
              className={cn(
                "num text-right",
                hovered.candle.close >= hovered.candle.open ? "text-bull" : "text-bear",
              )}
            >
              {formatPrice(hovered.candle.close, digits)}
            </span>
          </div>
          <div className="mt-1 flex items-center justify-between border-t border-line-soft pt-1 text-[8.5px]">
            <span
              className={cn(
                "font-semibold",
                hovered.candle.close >= hovered.candle.open ? "text-bull" : "text-bear",
              )}
            >
              {hovered.candle.close >= hovered.candle.open ? "Bullish" : "Bearish"}
            </span>
            <span className="text-ink-faint">
              {hovered.kind === "predicted"
                ? "AI prediction"
                : hovered.kind === "forming"
                  ? "live · unconfirmed"
                  : "confirmed"}
            </span>
          </div>
        </div>
      )}

      <div className="pointer-events-none absolute top-2 left-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[8.5px] text-ink-faint">
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2 bg-bull" /> bullish
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2 bg-bear" /> bearish
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2 border border-ink-muted/70" /> forming
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2 border border-dashed border-primary bg-primary/20" /> predicted
        </span>
      </div>
    </div>
  );
}
