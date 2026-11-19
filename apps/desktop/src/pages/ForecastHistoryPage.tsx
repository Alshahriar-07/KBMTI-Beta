import { useEffect, useState } from "react";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  BrainCircuit,
  ChevronDown,
  Clock3,
  Gauge,
  Minus,
  Play,
  RefreshCw,
  Target,
} from "lucide-react";

import { ForecastChart } from "@/components/market/ForecastChart";
import { AiNotice } from "@/components/ui/AiNotice";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Panel } from "@/components/ui/Panel";
import { Spinner } from "@/components/ui/Spinner";
import { usePolling } from "@/hooks/usePolling";
import { ApiError, api } from "@/lib/api";
import { activePredictedCandles } from "@/lib/forecast";
import {
  formatBrokerTime,
  formatPercent,
  formatPrice,
  formatTimeOnly,
} from "@/lib/format";
import type {
  Candle,
  ForecastAutomation,
  ForecastEvaluationStep,
  ForecastEvaluationSummary,
  ForecastLive,
  ForecastRun,
} from "@/lib/types";
import { cn } from "@/lib/utils";

function shortTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toISOString().slice(11, 16);
}

function directionTone(value: string | null | undefined): string {
  if (value === "bullish") return "text-bull";
  if (value === "bearish") return "text-bear";
  return "text-ink-muted";
}

function DirectionLabel({ value }: { value: string | null | undefined }) {
  const label = value ?? "—";
  const Icon =
    value === "bullish" ? ArrowUpRight : value === "bearish" ? ArrowDownRight : Minus;
  return (
    <span className={cn("inline-flex items-center gap-1 text-[10px]", directionTone(value))}>
      <Icon className="size-3" aria-hidden />
      <span className="capitalize">{label}</span>
    </span>
  );
}

function ResultBadge({ success }: { success: boolean }) {
  return (
    <Badge tone={success ? "success" : "danger"}>{success ? "Success" : "Failure"}</Badge>
  );
}

function AutoBadge({ automation }: { automation: ForecastAutomation | undefined }) {
  if (!automation?.enabled) {
    return <Badge tone="muted">Auto off</Badge>;
  }
  if (automation.waiting_for) {
    return (
      <Badge tone="warning" dot title={automation.waiting_for}>
        Waiting for PATRON
      </Badge>
    );
  }
  return (
    <Badge tone="info" dot title="Generates one forecast after every closed 15m candle">
      Auto · 15m close
    </Badge>
  );
}

function Stat({
  label,
  value,
  meta,
  tone,
}: {
  label: string;
  value: string;
  meta?: string;
  tone?: string;
}) {
  return (
    <div className="min-w-0 px-3 py-2">
      <p className="text-[9.5px] font-medium text-ink-faint">{label}</p>
      <p className={cn("num mt-0.5 truncate text-[12.5px] text-ink", tone)}>{value}</p>
      {meta && <p className="mt-0.5 truncate text-[9px] text-ink-faint">{meta}</p>}
    </div>
  );
}

function NextCandles({
  run,
  forming,
  lastClosed,
  digits,
}: {
  run: ForecastRun | null;
  forming: Candle | null;
  lastClosed: Candle | null;
  digits: number;
}) {
  const steps = activePredictedCandles(run, forming, lastClosed);
  const reference = run?.output?.meta?.reference_close ?? null;

  return (
    <Panel
      title="Next 6 predicted candles"
      icon={<Target className="size-3.5" />}
      meta={
        run
          ? `${steps.length} active · stored ${formatBrokerTime(run.created_at, true)}`
          : "waiting for the next closed bar"
      }
      bodyClassName="p-0"
    >
      {steps.length ? (
        <div className="grid grid-cols-2 divide-x divide-y divide-line-soft sm:grid-cols-3 lg:grid-cols-6 lg:divide-y-0">
          {steps.map((step, index) => {
            const bullish = step.close >= step.open;
            const base = index === 0 && reference !== null ? reference : steps[index - 1]?.close;
            const change = base ? ((step.close - base) / base) * 100 : null;
            const inProgress = forming !== null && step.timestamp_utc === forming.time;
            return (
              <div key={`${step.sequence}-${step.timestamp_utc}`} className="min-w-0 px-2.5 py-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[9px] font-semibold text-primary/85">
                    P{step.sequence + 1}
                  </span>
                  <span className="num text-[8.5px] text-ink-faint">
                    {shortTime(step.timestamp_utc)}
                  </span>
                </div>
                <p className={cn("num mt-1 text-[13px]", bullish ? "text-bull" : "text-bear")}>
                  {formatPrice(step.close, digits)}
                </p>
                <div className="mt-0.5 flex items-center justify-between gap-1">
                  <DirectionLabel value={bullish ? "bullish" : "bearish"} />
                  <span
                    className={cn(
                      "num text-[9px]",
                      (change ?? 0) > 0 ? "text-bull" : (change ?? 0) < 0 ? "text-bear" : "text-ink-muted",
                    )}
                  >
                    {formatPercent(change, 2)}
                  </span>
                </div>
                <p className="num mt-1 truncate text-[8.5px] text-ink-faint">
                  O {formatPrice(step.open, digits)} · H {formatPrice(step.high, digits)} · L{" "}
                  {formatPrice(step.low, digits)}
                </p>
                <Badge
                  tone={inProgress ? "warning" : "muted"}
                  className="mt-1.5 h-[16px] px-1 text-[8px]"
                >
                  {inProgress ? "in progress" : "pending"}
                </Badge>
              </div>
            );
          })}
        </div>
      ) : (
        <EmptyState
          icon={Target}
          title={run ? "No active predicted candle" : "No forecast stored yet"}
          description={
            run
              ? "The stored forecast has fully matured. The next six-candle forecast is generated automatically after the next 15m candle closes."
              : "PATRON predicts the next six closed 15m candles after each close. Nothing is drawn until a forecast has been persisted."
          }
        />
      )}
    </Panel>
  );
}

function PerformancePanel({ evaluation }: { evaluation: ForecastEvaluationSummary | null }) {
  const steps = evaluation?.steps_evaluated ?? 0;
  const last = evaluation?.last_evaluated ?? null;
  const accuracy =
    evaluation?.direction_accuracy === null || evaluation?.direction_accuracy === undefined
      ? "—"
      : `${(evaluation.direction_accuracy * 100).toFixed(1)}%`;

  return (
    <Panel
      title="Forecast performance"
      icon={<Gauge className="size-3.5" />}
      meta={`${evaluation?.runs_evaluated ?? 0} runs · ${steps} evaluated candles`}
      bodyClassName="p-0"
    >
      {steps === 0 ? (
        <EmptyState
          icon={Activity}
          title="No predictions evaluated yet"
          description="Each prediction is scored only after its target 15m candle closes. The first result appears automatically at the next close — no percentage is shown before then."
        />
      ) : (
        <>
          <div className="grid grid-cols-2 divide-x divide-y divide-line-soft sm:grid-cols-4 sm:divide-y-0">
            <Stat label="Successful" value={String(evaluation?.successful ?? 0)} tone="text-bull" />
            <Stat label="Failed" value={String(evaluation?.failed ?? 0)} tone="text-bear" />
            <Stat label="Direction accuracy" value={accuracy} />
            <Stat
              label="Avg close error"
              value={
                evaluation?.close_mae === null || evaluation?.close_mae === undefined
                  ? "—"
                  : formatPrice(evaluation.close_mae, 2)
              }
              meta={
                evaluation?.close_mape === null || evaluation?.close_mape === undefined
                  ? undefined
                  : `${(evaluation.close_mape * 100).toFixed(3)}% mean error`
              }
            />
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 border-t border-line-soft px-3 py-2 text-[9.5px] sm:grid-cols-4">
            <p className="text-ink-faint">
              Bullish calls{" "}
              <span className="num text-ink-muted">
                {evaluation?.bullish_accuracy === null || evaluation?.bullish_accuracy === undefined
                  ? "—"
                  : `${(evaluation.bullish_accuracy * 100).toFixed(1)}%`}
              </span>
            </p>
            <p className="text-ink-faint">
              Bearish calls{" "}
              <span className="num text-ink-muted">
                {evaluation?.bearish_accuracy === null || evaluation?.bearish_accuracy === undefined
                  ? "—"
                  : `${(evaluation.bearish_accuracy * 100).toFixed(1)}%`}
              </span>
            </p>
            <p className="text-ink-faint">
              Close within band{" "}
              <span className="num text-ink-muted">
                {evaluation?.band_coverage === null || evaluation?.band_coverage === undefined
                  ? "—"
                  : `${(evaluation.band_coverage * 100).toFixed(1)}%`}
              </span>
            </p>
            <p className="text-ink-faint">
              Doji threshold{" "}
              <span className="num text-ink-muted">
                {(((evaluation?.doji_threshold ?? 0.0002) * 100)).toFixed(2)}%
              </span>
            </p>
          </div>
          {last && (
            <div className="flex flex-wrap items-center gap-2 border-t border-line-soft px-3 py-2">
              <span className="text-[9.5px] text-ink-faint">Last evaluated</span>
              <span className="num text-[9.5px] text-ink-muted">
                {formatTimeOnly(last.target_time)} UTC
              </span>
              <DirectionLabel value={last.predicted_direction} />
              <span className="text-[9px] text-ink-faint">predicted</span>
              <DirectionLabel value={last.actual_direction} />
              <span className="text-[9px] text-ink-faint">actual</span>
              <ResultBadge success={last.success} />
              <span className="num ml-auto text-[9px] text-ink-faint">
                close error {formatPrice(last.abs_error, 2)}
              </span>
            </div>
          )}
          <p className="border-t border-line-soft px-3 py-2 text-[9px] leading-relaxed text-ink-faint">
            A candle is successful only when its predicted direction matches the realised
            direction. Close-price error is reported separately, so a close prediction cannot
            turn a wrong direction into a win.
          </p>
        </>
      )}
    </Panel>
  );
}

function RunComparison({
  detail,
  loading,
  digits,
}: {
  detail: ForecastRun | null;
  loading: boolean;
  digits: number;
}) {
  if (loading) {
    return (
      <div className="flex items-center gap-2 border-t border-line-soft px-3 py-3 text-[10px] text-ink-faint">
        <Spinner /> Loading stored forecast…
      </div>
    );
  }
  if (!detail) {
    return (
      <p className="border-t border-line-soft px-3 py-3 text-[9.5px] leading-relaxed text-ink-faint">
        Select an evaluated candle to compare the stored predicted OHLC with the realised OHLC.
      </p>
    );
  }
  const evaluation = new Map((detail.evaluation ?? []).map((row) => [row.step, row]));
  const rows = [...(detail.candles ?? [])]
    .sort((a, b) => a.sequence - b.sequence)
    .map((candle) => ({
      step: candle.sequence + 1,
      candle,
      evaluation: evaluation.get(candle.sequence + 1) ?? null,
    }));

  return (
    <div className="border-t border-line-soft">
      <div className="flex items-center justify-between gap-2 px-3 py-1.5">
        <span className="label-xs">Predicted vs actual</span>
        <span className="num truncate text-[9px] text-ink-faint">
          run {detail.id.slice(0, 8)} · {formatBrokerTime(detail.created_at, true)}
        </span>
      </div>
      <div className="max-h-[240px] overflow-auto">
        <table className="w-full border-collapse text-left">
          <thead className="sticky top-0 z-10 bg-surface-2">
            <tr className="text-[9px] text-ink-faint">
              <th className="h-6 px-2 font-medium">Step</th>
              <th className="h-6 px-2 font-medium">Target</th>
              <th className="h-6 px-2 font-medium">Direction</th>
              <th className="h-6 px-2 text-right font-medium">Pred close</th>
              <th className="h-6 px-2 text-right font-medium">Actual close</th>
              <th className="h-6 px-2 text-right font-medium">Error</th>
              <th className="h-6 px-2 font-medium">Result</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ step, candle, evaluation: row }) => (
              <tr key={step} className="border-t border-line-soft/60 text-[9.5px]">
                <td className="num h-6 px-2 text-ink-faint">P{step}</td>
                <td className="num h-6 px-2 text-ink-muted">{shortTime(candle.timestamp_utc)}</td>
                <td className="h-6 px-2">
                  <div className="flex items-center gap-1">
                    <DirectionLabel value={row?.predicted_direction ?? (candle.close >= candle.open ? "bullish" : "bearish")} />
                    {row && (
                      <>
                        <span className="text-[8px] text-ink-faint">→</span>
                        <DirectionLabel value={row.actual_direction} />
                      </>
                    )}
                  </div>
                </td>
                <td className="num h-6 px-2 text-right text-ink-muted">
                  {formatPrice(candle.close, digits)}
                </td>
                <td className="num h-6 px-2 text-right text-ink-muted">
                  {row ? formatPrice(row.actual_close, digits) : "—"}
                </td>
                <td className="num h-6 px-2 text-right text-ink-faint">
                  {row ? formatPrice(row.abs_error, 2) : "—"}
                </td>
                <td className="h-6 px-2">
                  {row ? (
                    <ResultBadge success={row.success} />
                  ) : (
                    <Badge tone="muted">waiting</Badge>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TimelinePanel({
  timeline,
  selectedId,
  onSelect,
  detail,
  detailLoading,
  digits,
}: {
  timeline: ForecastEvaluationStep[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  detail: ForecastRun | null;
  detailLoading: boolean;
  digits: number;
}) {
  return (
    <Panel
      title="Prediction timeline"
      icon={<Clock3 className="size-3.5" />}
      meta={`${timeline.length} recent evaluated candles`}
      bodyClassName="p-0"
    >
      {timeline.length ? (
        <div className="max-h-[250px] overflow-auto">
          {timeline.map((entry) => {
            const runId = entry.forecast_run_id ?? "";
            const selected = runId === selectedId;
            return (
              <button
                key={`${runId}-${entry.step}`}
                type="button"
                onClick={() => runId && onSelect(runId)}
                className={cn(
                  "flex w-full items-center gap-2 border-b border-line-soft/60 px-2.5 py-1.5 text-left transition-colors last:border-b-0 hover:bg-surface-2/50",
                  selected && "bg-light-blue/60",
                )}
              >
                <span className="num w-[38px] shrink-0 text-[9.5px] text-ink-muted">
                  {entry.target_time ? entry.target_time.slice(11, 16) : shortTime(entry.target_ts)}
                </span>
                <DirectionLabel value={entry.predicted_direction} />
                <span className="text-[8px] text-ink-faint">→</span>
                <DirectionLabel value={entry.actual_direction} />
                <span className="ml-auto shrink-0">
                  <ResultBadge success={entry.success} />
                </span>
                <span className="num w-[54px] shrink-0 text-right text-[8.5px] text-ink-faint">
                  {formatPrice(entry.abs_error, 2)}
                </span>
              </button>
            );
          })}
        </div>
      ) : (
        <EmptyState
          icon={Clock3}
          title="No evaluated predictions yet"
          description="Timeline entries appear only after a predicted target candle has closed and been scored. Predicted timestamps and results are never back-filled."
        />
      )}
      <RunComparison detail={detail} loading={detailLoading} digits={digits} />
    </Panel>
  );
}

function DiagnosticsDetails({
  live,
}: {
  live: ForecastLive;
}) {
  const status = live.status;
  const automation = status.automation;
  return (
    <details className="group rounded-lg border border-line bg-surface">
      <summary className="flex h-[34px] cursor-pointer list-none items-center gap-2 px-3">
        <ChevronDown className="size-3.5 shrink-0 text-ink-faint transition-transform group-open:rotate-180" />
        <span className="label-xs text-ink">Model diagnostics</span>
        <span className="ml-auto truncate text-[9px] text-ink-faint">
          {status.model_id} · {status.state} · checkpoint {status.checkpoint_exists ? "present" : "missing"}
        </span>
      </summary>
      <div className="grid gap-x-6 gap-y-1.5 border-t border-line-soft px-3 py-3 md:grid-cols-2 xl:grid-cols-3">
        <Diagnostic label="Model" value={status.model_id} />
        <Diagnostic label="State" value={status.state} />
        <Diagnostic label="Device" value={status.device ?? "cpu"} />
        <Diagnostic
          label="Parameters"
          value={status.trainable_parameters?.toLocaleString() ?? "—"}
        />
        <Diagnostic label="PyTorch" value={status.torch_version ?? "—"} />
        <Diagnostic
          label="Checkpoint SHA-256"
          value={status.checkpoint_sha256 ? `${status.checkpoint_sha256.slice(0, 16)}…` : "—"}
        />
        <Diagnostic label="Loaded" value={formatBrokerTime(status.loaded_at, true)} />
        <Diagnostic
          label="Inferences"
          value={`${status.inference_count ?? 0} · ${status.failure_count ?? 0} failed`}
        />
        <Diagnostic
          label="Latency"
          value={status.last_latency_ms ? `${status.last_latency_ms.toFixed(0)} ms` : "—"}
        />
        <Diagnostic label="Auto forecast" value={automation?.enabled ? "enabled" : "disabled"} />
        <Diagnostic
          label="Auto cycles"
          value={`${automation?.cycles ?? 0} · ${automation?.forecasts ?? 0} forecasts · ${automation?.steps_evaluated ?? 0} scored`}
        />
        <Diagnostic
          label="Last evaluated"
          value={formatBrokerTime(automation?.last_evaluated_at, true)}
        />
        <Diagnostic label="Contract" value="96 × 12 input · 6 candles / 90 min" />
        <Diagnostic label="Last error" value={status.last_error ?? "none"} />
        <Diagnostic label="Evaluation error" value={automation?.evaluation_error ?? "none"} />
      </div>
      <p className="border-t border-line-soft px-3 py-2 text-[9px] leading-relaxed text-ink-faint">
        PATRON is the only forecast engine. Predicted OHLC comes from its stored quantile
        payload; confidence, probabilities beyond the model heads and unsupported horizons are
        never invented. Detailed system metrics remain on the Model Status page.
      </p>
    </details>
  );
}

function Diagnostic({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[9.5px] text-ink-faint">{label}</p>
      <p className="num mt-0.5 truncate text-[10px] text-ink-muted" title={value}>
        {value}
      </p>
    </div>
  );
}

export function ForecastHistoryPage() {
  const live = usePolling<ForecastLive>("forecast-live", () => api.forecastLive(60), 5000);
  const data = live.data;
  const latest = data?.latest ?? null;
  const candles = data?.candles ?? [];
  const forming = data?.forming_candle ?? null;
  const lastClosed = candles.at(-1) ?? null;
  const digits = 2;
  const evaluation = data?.evaluation ?? null;
  const timeline = data?.timeline ?? [];
  const automation = data?.status?.automation;

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const defaultRunId = timeline[0]?.forecast_run_id ?? latest?.id ?? null;
  const activeRunId = selectedId ?? defaultRunId;
  const useLatest = activeRunId !== null && activeRunId === latest?.id;

  const selectedRun = usePolling<ForecastRun | null>(
    `forecast-run:${activeRunId ?? "none"}`,
    async () => (activeRunId && !useLatest ? api.forecastRun(activeRunId) : null),
    0,
  );

  useEffect(() => {
    if (selectedId && selectedId !== latest?.id) return;
    if (!selectedId && defaultRunId) setSelectedId(defaultRunId);
  }, [defaultRunId, selectedId, latest?.id]);

  const detail = useLatest ? latest : selectedRun.data;

  const price = data?.market.last ?? forming?.close ?? lastClosed?.close ?? null;
  const directionSource = forming ?? lastClosed;
  const directionBody =
    directionSource && directionSource.open
      ? (directionSource.close - directionSource.open) / directionSource.open
      : null;
  const doji = evaluation?.doji_threshold ?? 0.0002;
  const direction =
    directionBody === null
      ? null
      : Math.abs(directionBody) <= doji
        ? "neutral"
        : directionBody > 0
          ? "bullish"
          : "bearish";
  const directionChange =
    directionSource && directionSource.open
      ? ((directionSource.close - directionSource.open) / directionSource.open) * 100
      : null;
  const ready = Boolean(data?.status?.ai_available);
  const activeSteps = activePredictedCandles(latest, forming, lastClosed);
  const staleForecast =
    latest !== null &&
    activeSteps.length === 0 &&
    latest.candles !== null &&
    latest.candles !== undefined &&
    latest.candles.length > 0;

  const runNow = async () => {
    setRunning(true);
    setRunError(null);
    try {
      await api.runForecast({ symbol: "BTCUSDT", timeframe: "M15", horizon: 6 });
      live.reload();
    } catch (cause) {
      setRunError(cause instanceof ApiError ? cause.message : "Forecast run failed.");
    } finally {
      setRunning(false);
    }
  };

  if (!data && live.loading) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-[11px] text-ink-faint">
        <Spinner /> Loading Binance 15m candles and the stored PATRON forecast…
      </div>
    );
  }

  return (
    <div className="scroll-area h-full">
      <AiNotice title="PATRON live candle forecast · BTC/USDT 15m" compact>
        Forecasts are generated automatically from closed Binance 15m candles and stored
        before their targets occur. Predicted candles are outlined; realised candles are
        solid. Every prediction is immutable and scored only after its target closes.
      </AiNotice>

      <div className="flex flex-wrap items-end justify-between gap-3 px-3 pt-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-[15px] font-semibold tracking-[-0.01em] text-ink">
              Live forecast
            </h1>
            <Badge tone="accent">BTC/USDT · 15m</Badge>
            <AutoBadge automation={automation} />
            <Badge tone={data?.market.data_state === "live" ? "success" : "warning"} dot>
              {data?.market.data_state ?? "unavailable"}
            </Badge>
            <Badge tone={ready ? "success" : "warning"} dot>
              PATRON {ready ? "ready" : (data?.status.state ?? "unavailable").toLowerCase()}
            </Badge>
          </div>
          <p className="mt-1 text-[9.5px] text-ink-faint">
            {automation?.last_forecast_at
              ? `Last forecast ${formatBrokerTime(automation.last_forecast_at, true)}`
              : latest
                ? `Stored forecast ${formatBrokerTime(latest.created_at, true)}`
                : "Waiting for the first closed candle forecast"}
            {automation?.last_forecast_bar_at
              ? ` · input bar ${formatBrokerTime(automation.last_forecast_bar_at, true)}`
              : ""}
          </p>
        </div>
        <div className="flex items-end gap-4">
          <div className="text-right">
            <p className="num text-[26px] leading-none text-ink">{formatPrice(price, digits)}</p>
            <div className="mt-1 flex items-center justify-end gap-2">
              <DirectionLabel value={direction} />
              <span
                className={cn(
                  "num text-[10px]",
                  direction === "bullish"
                    ? "text-bull"
                    : direction === "bearish"
                      ? "text-bear"
                      : "text-ink-muted",
                )}
              >
                {formatPercent(directionChange, 3)}
              </span>
              <span className="text-[9.5px] text-ink-faint">
                {forming ? "Current 15m" : "Last closed"}
              </span>
            </div>
          </div>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void runNow()}
            disabled={running || !ready}
            icon={running ? <Spinner /> : <Play className="size-3.5" />}
            title="Run PATRON once now (automatic mode already does this at every close)"
          >
            Run now
          </Button>
        </div>
      </div>

      {(runError || live.error || data?.data_warning) && (
        <p className="mx-3 mt-2 border border-warn/25 bg-warn/[0.05] px-2.5 py-1.5 text-[9.5px] text-warn/90">
          {runError ?? live.error ?? data?.data_warning}
        </p>
      )}

      <div className="p-3">
        <Panel
          title="BTC/USDT · 15m"
          icon={<BrainCircuit className="size-3.5" />}
          meta={
            latest
              ? `forecast ${formatTimeOnly(latest.created_at)} UTC · ${latest.horizon} candles · ${latest.latency_ms?.toFixed(0) ?? "—"} ms`
              : "no stored forecast"
          }
          bodyClassName="p-0"
          className="overflow-hidden"
        >
          <div className="h-[clamp(360px,54vh,600px)] w-full">
            <ForecastChart history={candles} forming={forming} run={latest} digits={digits} />
          </div>
        </Panel>
      </div>

      {!ready && (
        <p className="mx-3 mb-3 border border-line-soft bg-soft/50 px-2.5 py-2 text-[9.5px] leading-relaxed text-ink-muted">
          PATRON is not ready, so no predicted candles are drawn. Actual Binance candles stay
          live and automatic forecasting resumes when the model reports ready.{" "}
          {data?.status.message}
        </p>
      )}

      {staleForecast && (
        <p className="mx-3 mb-3 border border-line-soft bg-soft/50 px-2.5 py-2 text-[9.5px] leading-relaxed text-ink-muted">
          The latest stored forecast has fully matured and is kept for evaluation. A new
          six-candle forecast will appear automatically after the next 15m close.
        </p>
      )}

      <div className="px-3 pb-3">
        <NextCandles run={latest} forming={forming} lastClosed={lastClosed} digits={digits} />
      </div>

      <div className="grid gap-3 px-3 pb-3 lg:grid-cols-[minmax(0,1fr)_380px]">
        <PerformancePanel evaluation={evaluation} />
        <TimelinePanel
          timeline={timeline}
          selectedId={activeRunId}
          onSelect={setSelectedId}
          detail={detail ?? null}
          detailLoading={selectedRun.loading && !useLatest}
          digits={digits}
        />
      </div>

      {data && (
        <div className="px-3 pb-3">
          <DiagnosticsDetails live={data} />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 pb-3 text-[8.5px] text-ink-faint">
        <span className="inline-flex items-center gap-1">
          <RefreshCw className="size-3" /> auto-refresh every 5s · closed-candle forecasts only
        </span>
        <span>Predicted candles are model output, not confirmed market data.</span>
        <span className="num">feed as of {formatBrokerTime(data?.as_of, true)}</span>
      </div>
    </div>
  );
}
