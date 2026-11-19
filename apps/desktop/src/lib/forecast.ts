import type { Candle, ForecastRun } from "@/lib/types";

/**
 * Select the authoritative run when the WebSocket and the polling fallback
 * briefly disagree. A newer poll must replace an older socket snapshot (and
 * vice versa); taking the first non-null source would pin the UI to whichever
 * arrived first and make a newly generated forecast look static.
 */
export function newestForecast(
  ...runs: Array<ForecastRun | null | undefined>
): ForecastRun | null {
  let newest: ForecastRun | null = null;
  let newestCreated = Number.NEGATIVE_INFINITY;
  let newestBar = Number.NEGATIVE_INFINITY;

  for (const run of runs) {
    if (!run) continue;
    const created = Date.parse(run.created_at);
    const createdMs = Number.isFinite(created) ? created : Number.NEGATIVE_INFINITY;
    const bar =
      typeof run.input_last_bar_at === "number" && Number.isFinite(run.input_last_bar_at)
        ? run.input_last_bar_at
        : Number.NEGATIVE_INFINITY;
    if (
      newest === null ||
      createdMs > newestCreated ||
      (createdMs === newestCreated && bar > newestBar)
    ) {
      newest = run;
      newestCreated = createdMs;
      newestBar = bar;
    }
  }
  return newest;
}

/**
 * Predicted candles that are still at or ahead of the current bar.
 *
 * Stored forecasts are keyed to the last closed input bar, so step 1 targets the
 * bar that is currently forming. Older targets have already closed and belong to
 * the evaluation timeline, never to the forward chart region.
 */
export function activePredictedCandles(
  run: ForecastRun | null,
  forming: Candle | null,
  lastClosed: Candle | null,
): NonNullable<ForecastRun["candles"]> {
  if (!run?.candles?.length) return [];
  const anchor = forming?.time ?? (lastClosed ? lastClosed.time + 900 : null);
  if (anchor === null) return [];
  return [...run.candles]
    .sort((a, b) => a.timestamp_utc - b.timestamp_utc)
    .filter((step) => step.timestamp_utc >= anchor);
}
