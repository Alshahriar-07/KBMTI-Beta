import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BrainCircuit,
  Crosshair,
  Gauge,
  Layers,
  Minus,
  ShieldAlert,
  Target,
  TrendingDown,
  TrendingUp,
} from "lucide-react";

import { PipelineReadinessPanel } from "@/components/assistant/PipelineReadinessPanel";
import { QwenRuntimePanel } from "@/components/assistant/QwenRuntimePanel";
import { ChartWorkspace } from "@/components/market/ChartWorkspace";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataRow } from "@/components/ui/DataRow";
import { EmptyState } from "@/components/ui/EmptyState";
import { GroupLabel, Panel } from "@/components/ui/Panel";
import { Spinner } from "@/components/ui/Spinner";
import { usePolling } from "@/hooks/usePolling";
import { api } from "@/lib/api";
import { formatBrokerTime, formatPrice } from "@/lib/format";
import { readinessTone } from "@/lib/readiness";
import {
  DEFAULT_OVERLAY_LAYERS,
  buildTradeChartOverlay,
  toggleLayer,
  type OverlayLayers,
  type TradeChartOverlay,
} from "@/lib/trade-visual";
import type {
  CandleSeries,
  Indicators,
  KieStatus,
  MarketIntelligence,
  MarketScenario,
  ScenarioId,
} from "@/lib/types";
import { useMarket } from "@/state/market-context";
import { cn } from "@/lib/utils";

function valuePrice(value: unknown): string {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? formatPrice(parsed, 2) : "—";
}

function number(value: unknown): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function distanceOnly(from: unknown, to: unknown): string {
  const start = number(from);
  const end = number(to);
  if (start === null || end === null) return "—";
  return formatPrice(Math.abs(end - start), 2);
}

function distanceFrom(from: unknown, to: unknown): string {
  const start = number(from);
  const end = number(to);
  if (start === null || end === null || start === 0) return "—";
  return `${formatPrice(Math.abs(end - start), 2)} · ${((Math.abs(end - start) / start) * 100).toFixed(2)}%`;
}

function decisionTone(decision: MarketIntelligence["decision"]) {
  return decision === "LONG"
    ? "success"
    : decision === "SHORT"
      ? "danger"
      : decision === "WAIT"
        ? "warning"
        : "muted";
}

function assessmentTone(status: string) {
  return status === "VALID"
    ? "success"
    : status === "LOW_CONFIDENCE" || status === "STALE"
      ? "warning"
      : status === "CONFLICTING_EVIDENCE" || status === "INVALID"
        ? "danger"
        : "muted";
}

function ScenarioIcon({ bias }: { bias: MarketScenario["bias"] }) {
  if (bias === "BULLISH") return <TrendingUp className="size-3.5" aria-hidden />;
  if (bias === "BEARISH") return <TrendingDown className="size-3.5" aria-hidden />;
  return <ArrowRight className="size-3.5" aria-hidden />;
}

function LayerToggle({
  label,
  active,
  onClick,
  icon,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  icon: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-[25px] items-center gap-1.5 rounded-[5px] border px-2 text-[9.5px] font-medium transition-colors",
        active
          ? "border-primary/35 bg-primary/10 text-primary"
          : "border-line-soft bg-transparent text-ink-faint hover:border-line hover:text-ink-muted",
      )}
    >
      {icon}
      {label}
    </button>
  );
}

function DecisionBadge({ data }: { data: MarketIntelligence }) {
  return (
    <Badge tone={decisionTone(data.decision)} dot>
      {data.decision}
    </Badge>
  );
}

function NearestLevels({ data, overlay }: { data: MarketIntelligence; overlay: TradeChartOverlay | null }) {
  const last = number(data.market_snapshot.last_price);
  const levels = (overlay?.lines ?? []).filter(
    (line) => line.tone === "support" || line.tone === "resistance",
  );
  const support = last === null
    ? null
    : levels
        .filter((line) => line.tone === "support" && line.price < last)
        .sort((a, b) => b.price - a.price)[0] ?? null;
  const resistance = last === null
    ? null
    : levels
        .filter((line) => line.tone === "resistance" && line.price > last)
        .sort((a, b) => a.price - b.price)[0] ?? null;
  return (
    <>
      <DataRow
        label="Nearest support"
        value={support ? formatPrice(support.price, 2) : "Unavailable"}
        toneClassName={support ? "text-bull" : "text-ink-faint"}
      />
      <DataRow
        label="Nearest resistance"
        value={resistance ? formatPrice(resistance.price, 2) : "Unavailable"}
        toneClassName={resistance ? "text-bear" : "text-ink-faint"}
      />
    </>
  );
}

function ScenarioCard({
  scenario,
  active,
  onShow,
}: {
  scenario: MarketScenario;
  active: boolean;
  onShow: () => void;
}) {
  const focused = active;
  const tone =
    scenario.bias === "BULLISH" ? "bull" : scenario.bias === "BEARISH" ? "bear" : "muted";
  return (
    <article
      className={cn(
        "flex min-w-0 flex-col rounded-[8px] border bg-surface p-2.5",
        scenario.available ? "border-line" : "border-dashed border-line-soft",
      )}
    >
      <header className="flex items-start gap-2">
        <span
          className={cn(
            "mt-0.5",
            tone === "bull" ? "text-bull" : tone === "bear" ? "text-bear" : "text-ink-faint",
          )}
        >
          <ScenarioIcon bias={scenario.bias} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-[10.5px] font-semibold text-ink">{scenario.title}</h3>
          <p className="mt-0.5 text-[8.5px] text-ink-faint">{scenario.condition}</p>
        </div>
        <Badge tone={scenario.available ? (scenario.bias === "BULLISH" ? "success" : scenario.bias === "BEARISH" ? "danger" : "warning") : "muted"}>
          {scenario.available ? "conditional" : "unavailable"}
        </Badge>
      </header>

      {scenario.available ? (
        <>
          <div className="mt-2 grid grid-cols-3 gap-1 border-y border-line-soft py-1.5">
            {[
              ["Trigger", scenario.trigger],
              ["Target", scenario.target],
              ["Invalidation", scenario.invalidation],
            ].map(([label, price]) => (
              <div key={String(label)} className="min-w-0">
                <p className="text-[8px] text-ink-faint">{label}</p>
                <p className="num mt-0.5 truncate text-[9.5px] text-ink-muted">
                  {price === null ? "Unavailable" : formatPrice(Number(price), 2)}
                </p>
              </div>
            ))}
          </div>
          <p className="mt-1.5 text-[9px] leading-snug text-ink-faint">
            <span className="font-medium text-ink-muted">Confirm:</span> {scenario.confirmation}
          </p>
          <p className="mt-1 text-[9px] leading-snug text-ink-faint">
            <span className="font-medium text-ink-muted">Invalidate:</span>{" "}
            {scenario.invalidation_text}
          </p>
          <p className="mt-1 text-[9px] leading-snug text-ink-faint">
            <span className="font-medium text-ink-muted">Structure:</span>{" "}
            {scenario.structure || "unavailable"}
          </p>
          <div className="mt-1.5 grid gap-1 text-[8.5px] leading-snug">
            {scenario.evidence_for.slice(0, 2).map((item) => (
              <p key={item} className="text-bull/80">+ {item}</p>
            ))}
            {scenario.evidence_against.slice(0, 1).map((item) => (
              <p key={item} className="text-bear/80">− {item}</p>
            ))}
          </div>
          <Button size="sm" variant="ghost" className="mt-2 w-fit" onClick={onShow}>
            {focused ? "Focused on chart" : "Focus scenario on chart"}
          </Button>
        </>
      ) : (
        <p className="mt-2 text-[9px] leading-relaxed text-ink-faint">
          {scenario.unavailable_reason ?? "Verified levels are insufficient for this scenario."}
        </p>
      )}
      <p className="mt-1.5 border-t border-line-soft/70 pt-1 text-[8px] text-ink-faint">
        Data: {scenario.data_as_of ? formatBrokerTime(scenario.data_as_of) : "unavailable"} ·{" "}
        <span className={scenario.data_is_stale ? "text-warn" : undefined}>
          {scenario.data_is_stale ? "stale" : "fresh"}
        </span>
      </p>
    </article>
  );
}

function ScenarioGrid({
  scenarios,
  layers,
  focusedScenario,
  onShow,
  onShowAll,
}: {
  scenarios: MarketScenario[];
  layers: OverlayLayers;
  focusedScenario: ScenarioId | null;
  onShow: (id: ScenarioId) => void;
  onShowAll: () => void;
}) {
  return (
    <Panel
      title="Possible next market movements"
      icon={<Activity className="size-3.5" />}
      meta={
        <button
          type="button"
          onClick={onShowAll}
          className="text-[9px] text-primary hover:underline"
        >
          show all scenarios
        </button>
      }
      bodyClassName="p-2"
    >
      <p className="mb-2 text-[9px] leading-relaxed text-ink-faint">
        These are conditional level-to-level paths, not guaranteed future candles. Each path is
        drawn only when the verified trigger and target exist.
      </p>
      <div className="grid gap-2 md:grid-cols-2 2xl:grid-cols-3">
        {scenarios.map((scenario) => (
          <ScenarioCard
            key={scenario.id}
            scenario={scenario}
            active={layers.scenarios && focusedScenario === scenario.id}
            onShow={() => onShow(scenario.id)}
          />
        ))}
      </div>
    </Panel>
  );
}

function TradeRecommendation({ data }: { data: MarketIntelligence }) {
  const plan = data.trade_plan;
  return (
    <Panel title="Trade recommendation" icon={<Target className="size-3.5" />} bodyClassName="p-0">
      <div className="flex items-start gap-2 px-3 py-3">
        <div className="min-w-0 flex-1">
          <p className="label-xs">Deterministic decision</p>
          <div className="mt-1 flex flex-wrap items-baseline gap-2">
            <span
              className={cn(
                "text-[24px] font-semibold leading-none tracking-[0.02em]",
                data.decision === "LONG"
                  ? "text-bull"
                  : data.decision === "SHORT"
                    ? "text-bear"
                    : data.decision === "WAIT"
                      ? "text-warn"
                      : "text-ink-muted",
              )}
            >
              {data.decision.replaceAll("_", " ")}
            </span>
            {plan && <Badge tone="info">{plan.direction} setup</Badge>}
          </div>
          <p className="mt-1.5 text-[10px] leading-relaxed text-ink-muted">
            {data.decision_reason}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <DecisionBadge data={data} />
          <Badge tone={readinessTone(data.readiness.strategy.status)}>
            Gate {data.readiness.strategy.status}
          </Badge>
          <Badge tone="muted">{data.readiness.execution.status}</Badge>
        </div>
      </div>

      {plan ? (
        <>
          <GroupLabel>Plan geometry · {plan.strategy_id} v{plan.strategy_version}</GroupLabel>
          <DataRow
            label="Entry zone"
            value={`${valuePrice(plan.entry_zone.lower)} – ${valuePrice(plan.entry_zone.upper)}`}
          />
          <DataRow label="Suggested entry" value={valuePrice(plan.suggested_entry)} />
          <DataRow label="Confirmation boundary" value={valuePrice(plan.confirmation_level)} />
          <DataRow
            label="Structural stop"
            value={valuePrice(plan.stop_loss)}
            toneClassName="text-bear"
          />
          <DataRow
            label="Stop distance"
            value={distanceFrom(plan.suggested_entry, plan.stop_loss)}
            toneClassName="text-bear"
          />
          {plan.take_profits.map((target) => (
            <DataRow
              key={target.label}
              label={`${target.label} · ${target.method}`}
              value={valuePrice(target.price)}
              hint={`${Number(target.risk_multiple).toFixed(2)}R`}
              toneClassName="text-bull"
            />
          ))}
          <DataRow
            label="Target distances"
            value={plan.take_profits
              .map((target) => distanceOnly(plan.suggested_entry, target.price))
              .join(" / ")}
          />
          <DataRow
            label="Risk / reward"
            value={`${Number(plan.risk_reward.rr_tp1).toFixed(2)} / ${Number(plan.risk_reward.rr_tp2).toFixed(2)} / ${Number(plan.risk_reward.rr_tp3).toFixed(2)}`}
          />
          <DataRow label="Setup expires" value={formatBrokerTime(plan.expires_at)} />
          <DataRow label="Risk validation" value={plan.risk_validation_status} />
          <p className="border-t border-line-soft/70 px-3 py-1.5 text-[8.5px] leading-relaxed text-ink-faint">
            Breakout and retest levels are not emitted by this {plan.entry_zone.anchor_type.replaceAll("_", " ").toLowerCase()} plan. The deterministic confirmation boundary and stop remain authoritative; no retest price is invented.
          </p>
          <GroupLabel>Confirmation requirements</GroupLabel>
          <ConditionList
            items={plan.confirmation_requirements}
            empty="No additional confirmation rules were emitted by the planner."
          />
          <GroupLabel>Invalidation conditions</GroupLabel>
          <ConditionList
            items={plan.invalidation_conditions}
            empty="The stop level is the only invalidation boundary."
          />
          <p className="border-t border-line-soft/70 px-3 py-2 text-[8.5px] leading-relaxed text-ink-faint">
            Setup expiration is a planning boundary, not an instruction to enter. Execution is
            disabled and no position size exists.
          </p>
        </>
      ) : (
        <div className="border-t border-line-soft px-3 py-3 text-[10px] leading-relaxed text-ink-faint">
          No deterministic trade plan exists. {data.decision === "WAIT" || data.decision === "NO_TRADE"
            ? "The assistant is explicitly staying out; it is not forcing a setup from a forecast."
            : "The chart can still show structure and scenarios, but no entry, stop or target is fabricated."}
        </div>
      )}
    </Panel>
  );
}

function ConditionList({ items, empty }: { items: string[]; empty: string }) {
  return items.length ? (
    <ul className="space-y-1 px-3 py-2">
      {items.map((item) => (
        <li key={item} className="flex gap-2 text-[9.5px] leading-relaxed text-ink-faint">
          <span className="mt-[6px] size-1 shrink-0 bg-ink-faint/60" />
          {item}
        </li>
      ))}
    </ul>
  ) : (
    <p className="px-3 py-2 text-[9.5px] leading-relaxed text-ink-faint">{empty}</p>
  );
}

function ForecastPanel({ data }: { data: MarketIntelligence }) {
  const source = data.forecast_source;
  const assessment = data.forecast_assessment;
  return (
    <Panel title="PATRON forecast assessment" icon={<BrainCircuit className="size-3.5" />} bodyClassName="p-0">
      <div className="flex flex-wrap items-center gap-1.5 px-3 py-2">
        <Badge tone={assessmentTone(assessment.status)} dot>
          {assessment.status.replaceAll("_", " ")}
        </Badge>
        <Badge tone={assessment.usable_in_decision ? "info" : "warning"}>
          {assessment.usable_in_decision ? "usable as evidence" : "excluded from decision"}
        </Badge>
        <span className="ml-auto text-[8.5px] text-ink-faint">{assessment.confidence_score === null ? "no confidence score" : ""}</span>
      </div>
      <DataRow
        label="Forecast direction"
        value={assessment.forecast_direction ?? "Unavailable"}
        toneClassName={assessment.forecast_direction === "BULLISH" ? "text-bull" : assessment.forecast_direction === "BEARISH" ? "text-bear" : "text-ink-faint"}
      />
      <DataRow
        label="Freshness"
        value={
          assessment.freshness_seconds === null
            ? "Unavailable"
            : `${Math.max(0, Math.round(assessment.freshness_seconds / 60))} min`
        }
      />
      <DataRow
        label="Median displacement"
        value={
          assessment.median_path_atr === null
            ? "Unavailable"
            : `${assessment.median_path_atr.toFixed(2)} ATR`
        }
        hint={assessment.horizon_minutes ? `${assessment.horizon_minutes} min horizon` : undefined}
      />
      <DataRow
        label="Direction conflict"
        value={
          assessment.direction_conflict_material === null
            ? "—"
            : assessment.direction_conflict_material
              ? "Material"
              : "Below threshold"
        }
        toneClassName={assessment.direction_conflict_material ? "text-warn" : undefined}
      />
      <DataRow label="Source model" value={source?.model_version ?? "Unavailable"} />
      <DataRow label="Source as of" value={source?.forecast_as_of ? formatBrokerTime(source.forecast_as_of) : "—"} />
      <DataRow label="Median path" value={source?.range_quantiles.length ? `${source.range_quantiles.length} steps` : "Unavailable"} />
      <div className="border-t border-line-soft px-3 py-2">
        {assessment.reasons.length ? (
          <ul className="space-y-1">
            {assessment.reasons.slice(0, 3).map((reason) => (
              <li key={reason} className="text-[9px] leading-snug text-ink-faint">· {reason}</li>
            ))}
          </ul>
        ) : (
          <p className="text-[9px] leading-snug text-ink-faint">No assessment reasons were emitted.</p>
        )}
        <p className="mt-1.5 text-[8.5px] leading-relaxed text-ink-faint">
          Qwen explains this evidence. It cannot change a forecast number, the decision, or a risk
          level. {data.ai_forecast_interpretation}
        </p>
      </div>
    </Panel>
  );
}

function TradeManagement({ data }: { data: MarketIntelligence }) {
  const plan = data.trade_plan;
  const tp1 = plan ? valuePrice(plan.take_profits[0]?.price) : "—";
  const tp2 = plan ? valuePrice(plan.take_profits[1]?.price) : "—";
  const tp3 = plan ? valuePrice(plan.take_profits[2]?.price) : "—";
  return (
    <Panel title="Trade management" icon={<ShieldAlert className="size-3.5" />} bodyClassName="p-0">
      <div className="px-3 py-2.5 text-[9.5px] leading-relaxed text-ink-faint">
        Guidance is conditional and educational. The assistant never moves a stop, changes a
        target, or opens/closes a position automatically.
      </div>
      <div className="grid md:grid-cols-2 md:divide-x md:divide-line">
        <div>
          <GroupLabel>Before entry</GroupLabel>
          <ConditionList
            items={
              plan
                ? [
                    ...plan.confirmation_requirements,
                    `Wait for a verified trigger; setup expires ${formatBrokerTime(plan.expires_at)}.`,
                  ]
                : ["No setup is active. Wait for a fresh deterministic plan and risk validation."]
            }
            empty="No confirmation rules were emitted."
          />
        </div>
        <div>
          <GroupLabel>At the targets</GroupLabel>
          <div className="px-3 py-2 text-[9px] leading-relaxed text-ink-faint">
            TP1 {tp1} · TP2 {tp2} · TP3 {tp3}. Reassess structure, momentum and the forecast
            assessment at each level. Do not assume a target will fill.
          </div>
        </div>
      </div>
      <GroupLabel>Risk boundary</GroupLabel>
      <p className="px-3 py-2 text-[9.5px] leading-relaxed text-ink-faint">
        {plan
          ? `The planned invalidation is ${valuePrice(plan.stop_loss)}. A close through it invalidates the idea; any change requires a new deterministic plan and risk validation.`
          : "No stop exists without a deterministic plan. Do not infer one from a scenario path."}
      </p>
    </Panel>
  );
}

function ChartLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line-soft bg-surface/70 px-2.5 py-1 text-[8.5px] text-ink-faint">
      <span className="inline-flex items-center gap-1"><span className="size-2 bg-bull" /> actual up</span>
      <span className="inline-flex items-center gap-1"><span className="size-2 bg-bear" /> actual down</span>
      <span className="inline-flex items-center gap-1"><span className="h-2 w-3 border border-primary bg-primary/15" /> entry zone</span>
      <span className="inline-flex items-center gap-1"><span className="h-2 w-3 border border-bear/60 bg-bear/10" /> risk</span>
      <span className="inline-flex items-center gap-1"><span className="h-2 w-3 border border-bull/60 bg-bull/10" /> reward</span>
      <span className="inline-flex items-center gap-1"><span className="size-2 border border-primary/45 bg-primary/15" /> PATRON predicted</span>
      <span className="inline-flex items-center gap-1"><span className="h-0 w-4 border-t border-dashed border-primary" /> PATRON median</span>
      <span className="inline-flex items-center gap-1"><span className="h-0 w-4 border-t border-dashed border-ink-faint" /> conditional scenario</span>
      <span className="ml-auto">labels: BOS / CHoCH / HH / HL / LH / LL / sweep</span>
    </div>
  );
}

function AnnotationStrip({
  overlay,
  selectedId,
  onSelect,
}: {
  overlay: TradeChartOverlay | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const annotations = overlay?.annotations ?? [];
  const selected = annotations.find((item) => item.id === selectedId) ?? null;
  return (
    <div className="border-t border-line-soft bg-surface px-2.5 py-2">
      <div className="flex items-center gap-2">
        <p className="label-xs shrink-0">Chart annotations</p>
        <div className="flex min-w-0 flex-1 gap-1 overflow-x-auto">
          {annotations.length ? (
            annotations.slice(0, 16).map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => onSelect(item.id)}
                className={cn(
                  "shrink-0 rounded-[4px] border px-1.5 py-0.5 text-left text-[8.5px] transition-colors",
                  selectedId === item.id
                    ? "border-primary/45 bg-primary/10 text-primary"
                    : "border-line-soft text-ink-faint hover:border-line-strong hover:text-ink-muted",
                )}
              >
                {item.label}
              </button>
            ))
          ) : (
            <span className="text-[8.5px] text-ink-faint">
              No annotation layers are active. Enable trade levels or structure above.
            </span>
          )}
        </div>
      </div>
      {selected ? (
        <p className="mt-1 text-[9px] leading-snug text-ink-faint">{selected.detail}</p>
      ) : (
        <p className="mt-1 text-[9px] leading-snug text-ink-faint">
          Select an annotation for its calculation source and meaning.
        </p>
      )}
    </div>
  );
}

export function AssistantPage() {
  const { stream, settings } = useMarket();
  const snapshot = stream.snapshot;
  const symbol = settings?.symbol ?? snapshot?.symbol ?? "BTCUSDT";
  const timeframe = settings?.timeframe ?? snapshot?.timeframe ?? "M15";
  const limit = settings?.candle_limit ?? 500;
  const candleTime = snapshot?.candle_time ?? 0;
  const scopeSupported =
    symbol.replace("/", "").toUpperCase() === "BTCUSDT" && timeframe === "M15";

  const candles = usePolling<CandleSeries>(
    `assistant-chart-candles:${symbol}:${timeframe}:${candleTime}`,
    () => api.candles(limit),
    15_000,
  );
  const indicators = usePolling<Indicators>(
    `assistant-chart-indicators:${symbol}:${timeframe}:${candleTime}`,
    () => api.indicators(limit),
    20_000,
  );
  const intelligence = usePolling<MarketIntelligence | null>(
    `assistant-visual:${scopeSupported ? candleTime : "out-of-scope"}`,
    () => (scopeSupported ? api.marketIntelligence(true) : Promise.resolve(null)),
    60_000,
  );
  const kie = usePolling<KieStatus>("kie-runtime-status", () => api.kieStatus(), 5_000);
  const [retryingQwen, setRetryingQwen] = useState(false);
  const [retryingAnalysis, setRetryingAnalysis] = useState(false);
  const [qwenActionError, setQwenActionError] = useState<string | null>(null);
  const [layers, setLayers] = useState<OverlayLayers>(DEFAULT_OVERLAY_LAYERS);
  const [focusedScenario, setFocusedScenario] = useState<ScenarioId | null>(null);
  const [selectedAnnotation, setSelectedAnnotation] = useState<string | null>(null);
  const data = intelligence.data;
  const reloadIntelligence = intelligence.reload;
  useEffect(() => {
    if (kie.data?.ready && data?.ai_status.status === "INITIALIZING") {
      reloadIntelligence();
    }
  }, [kie.data?.ready, data?.ai_status.status, reloadIntelligence]);
  useEffect(() => {
    if (retryingAnalysis && !intelligence.loading) setRetryingAnalysis(false);
  }, [retryingAnalysis, intelligence.loading]);
  const overlay = useMemo(
    () =>
      data
        ? buildTradeChartOverlay(
            data,
            candles.data?.candles ?? [],
            layers,
            focusedScenario,
          )
        : null,
    [data, candles.data?.candles, layers, focusedScenario],
  );
  const error = intelligence.error ?? candles.error ?? indicators.error;

  const retryAnalysis = () => {
    // One explicit retry at a time. The backend also serializes inference, so a
    // double click cannot create two generations.
    if (retryingAnalysis || intelligence.loading) return;
    setRetryingAnalysis(true);
    reloadIntelligence();
  };

  const retryQwen = async () => {
    setRetryingQwen(true);
    setQwenActionError(null);
    try {
      await api.kieLoad();
      kie.reload();
      intelligence.reload();
    } catch (cause) {
      setQwenActionError(cause instanceof Error ? cause.message : "Qwen could not be initialized.");
    } finally {
      setRetryingQwen(false);
    }
  };

  if (!scopeSupported) {
    return (
      <div className="scroll-area h-full p-4">
        <EmptyState
          icon={Gauge}
          title="Visual assistant is scoped to BTCUSDT M15"
          description="This workspace is intentionally limited to the verified Binance BTCUSDT 15-minute market. Forex pairs are not enabled until a verified provider, pip contract, and instrument-specific tests exist."
        />
      </div>
    );
  }

  if (intelligence.loading && !data && !candles.data) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-[10.5px] text-ink-faint">
        <Spinner /> Building the validated market and trade plan…
      </div>
    );
  }

  return (
    <div className="scroll-area h-full">
      <header className="sticky top-0 z-20 border-b border-line bg-surface/95 px-3 py-2 backdrop-blur-sm">
        <div className="mx-auto flex max-w-[1700px] flex-wrap items-center gap-2">
          <span className="label-xs">Visual AI trading assistant</span>
          {data ? (
            <>
              <DecisionBadge data={data} />
              <Badge tone={readinessTone(data.readiness.market.status)} dot>
                Market {data.readiness.market.status}
              </Badge>
              <Badge tone={readinessTone(data.readiness.patron.status)}>
                PATRON {data.readiness.patron.status}
              </Badge>
              <Badge tone={readinessTone(data.readiness.qwen.status)}>
                Qwen {data.readiness.qwen.status}
              </Badge>
              <Badge tone={readinessTone(data.readiness.strategy.status)}>
                Gate {data.readiness.strategy.status}
              </Badge>
              <Badge tone={readinessTone(data.readiness.trade_plan.status)}>
                Plan {data.readiness.trade_plan.status}
              </Badge>
              <Badge tone="muted">Execution {data.readiness.execution.status}</Badge>
            </>
          ) : (
            <Badge tone="muted" dot>
              LOADING
            </Badge>
          )}
          <span className="num ml-auto text-[9px] text-ink-faint">
            {symbol} · {timeframe} · as of {data ? formatBrokerTime(data.data_as_of) : "—"}
          </span>
        </div>
      </header>

      {error && (
        <div className="mx-auto mt-2 flex max-w-[1700px] flex-wrap items-start gap-2 border-y border-warn/20 bg-warn/[0.04] px-3 py-1.5 text-[10px] text-warn/90">
          <AlertTriangle className="mt-[1px] size-3 shrink-0" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="leading-relaxed">{error}</p>
            {intelligence.requestId && (
              <p className="num mt-0.5 text-[8px] text-ink-faint">
                correlation id: {intelligence.requestId}
              </p>
            )}
          </div>
          {intelligence.error && intelligence.retryable && (
            <Button
              size="sm"
              variant="secondary"
              onClick={retryAnalysis}
              disabled={retryingAnalysis || intelligence.loading}
            >
              {retryingAnalysis || intelligence.loading ? "Retrying…" : "Retry analysis"}
            </Button>
          )}
        </div>
      )}

      <div className="mx-auto grid max-w-[1700px] gap-2 p-2 xl:grid-cols-[minmax(0,1fr)_390px]">
        <main className="min-w-0 space-y-2">
          <section className="overflow-hidden rounded-[10px] border border-line bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.16)]">
            <div className="flex flex-wrap items-center gap-1.5 border-b border-line-soft bg-surface-2/25 px-2.5 py-1.5">
              <span className="mr-1 inline-flex items-center gap-1 text-[9px] font-medium text-ink-faint">
                <Layers className="size-3" aria-hidden /> Overlays
              </span>
              <LayerToggle
                label="Trade levels"
                active={layers.trade}
                icon={<Target className="size-3" />}
                onClick={() => setLayers((current) => toggleLayer(current, "trade"))}
              />
              <LayerToggle
                label="S/R + liquidity"
                active={layers.levels}
                icon={<Minus className="size-3" />}
                onClick={() => setLayers((current) => toggleLayer(current, "levels"))}
              />
              <LayerToggle
                label="Structure"
                active={layers.structure}
                icon={<Crosshair className="size-3" />}
                onClick={() => setLayers((current) => toggleLayer(current, "structure"))}
              />
              <LayerToggle
                label="PATRON"
                active={layers.forecast}
                icon={<BrainCircuit className="size-3" />}
                onClick={() => setLayers((current) => toggleLayer(current, "forecast"))}
              />
              <LayerToggle
                label="Scenarios"
                active={layers.scenarios}
                icon={<Activity className="size-3" />}
                onClick={() => {
                  setFocusedScenario(null);
                  setLayers((current) => toggleLayer(current, "scenarios"));
                }}
              />
              <LayerToggle
                label="Risk / reward"
                active={layers.riskReward}
                icon={<ShieldAlert className="size-3" />}
                onClick={() => setLayers((current) => toggleLayer(current, "riskReward"))}
              />
              <span className="ml-auto hidden text-[8.5px] text-ink-faint sm:block">
                dashed = hypothetical / source evidence
              </span>
            </div>
            <ChartLegend />
            <div className="h-[clamp(360px,52vh,570px)] min-h-[340px]">
              <ChartWorkspace
                candles={candles.data}
                indicators={indicators.data}
                loading={candles.loading || indicators.loading}
                showFooter={false}
                overlay={overlay}
              />
            </div>
            <AnnotationStrip
              overlay={overlay}
              selectedId={selectedAnnotation}
              onSelect={setSelectedAnnotation}
            />
          </section>

          {data ? (
            <ScenarioGrid
              scenarios={data.chart_overlay.scenarios}
              layers={layers}
              focusedScenario={focusedScenario}
              onShow={(id) => {
                setFocusedScenario(id);
                setLayers((current) => ({ ...current, scenarios: true }));
              }}
              onShowAll={() => {
                setFocusedScenario(null);
                setLayers((current) => ({ ...current, scenarios: true }));
              }}
            />
          ) : (
            <Panel title="Possible next market movements" bodyClassName="p-3 text-[10px] text-ink-faint">
              Waiting for the validated market, structure and trade plan.
            </Panel>
          )}

          {data ? <TradeManagement data={data} /> : null}

          <Panel title="Scope and multi-timeframe" icon={<Gauge className="size-3.5" />} bodyClassName="p-0">
            <DataRow label="Verified scope" value="BTCUSDT · M15" />
            <DataRow label="Other timeframes" value="Not computed" />
            <DataRow label="Forex" value="Not enabled" />
            <p className="px-3 py-2 text-[9px] leading-relaxed text-ink-faint">
              No multi-timeframe alignment or Forex pip calculation is claimed here. Adding
              another instrument requires a verified provider, symbol handling, spread/pip
              contracts and separate tests; crypto price arithmetic is not reused for FX.
            </p>
          </Panel>
        </main>

        <aside className="min-w-0 space-y-2">
          <QwenRuntimePanel
            status={kie.data}
            error={qwenActionError ?? kie.error}
            retrying={retryingQwen}
            onRetry={() => void retryQwen()}
          />
          {data ? <PipelineReadinessPanel readiness={data.readiness} /> : null}
          {!data ? (
            <Panel title="AI trade analysis" icon={<BrainCircuit className="size-3.5" />}>
              <div className="flex items-center gap-2 text-[10px] text-ink-faint">
                {intelligence.loading ? <Spinner /> : <AlertTriangle className="size-3.5 text-warn" />}
                {intelligence.loading
                  ? "Waiting for the validated response. The chart remains live; no setup is fabricated."
                  : "The validated response is unavailable. No entry, stop or target is shown."}
              </div>
            </Panel>
          ) : (
            <>
              <Panel title="AI market view" icon={<BrainCircuit className="size-3.5" />} bodyClassName="p-0">
                <div className="px-3 py-2.5">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <DecisionBadge data={data} />
                    <Badge tone={data.is_stale ? "warning" : "info"}>{data.is_stale ? "stale" : "fresh"}</Badge>
                    <Badge tone="muted">PATRON {data.forecast_assessment.status.replaceAll("_", " ")}</Badge>
                  </div>
                  <p className="mt-2 text-[10px] leading-relaxed text-ink-muted">
                    {data.ai_market_interpretation}
                  </p>
                  {!data.ai_status.used && data.ai_status.error && (
                    <p className="mt-1.5 text-[9px] leading-snug text-warn/90">
                      AI {data.ai_status.status.toLowerCase()}: {data.ai_status.error}
                    </p>
                  )}
                </div>
                <GroupLabel>Current market condition</GroupLabel>
                <DataRow label="Bias" value={data.market_condition.direction} />
                <DataRow label="Trend" value={`${data.market_condition.trend} · ${data.market_condition.trend_strength}`} />
                <DataRow label="Momentum" value={`${data.market_condition.momentum} · ${data.market_condition.momentum_phase}`} />
                <DataRow label="Volatility" value={`${data.market_condition.volatility} · ${data.market_condition.volatility_phase}`} />
                <DataRow label="Structure" value={data.market_condition.structure} />
                <DataRow label="Regime" value={data.market_condition.regime} />
                <NearestLevels data={data} overlay={overlay} />
                <DataRow
                  label="Data as of"
                  value={formatBrokerTime(data.data_as_of)}
                  toneClassName={data.is_stale ? "text-warn" : undefined}
                />
              </Panel>

              <TradeRecommendation data={data} />

              <Panel title="Why this trade?" icon={<ShieldAlert className="size-3.5" />} bodyClassName="p-0">
                <div className="px-3 py-2.5 text-[10px] leading-relaxed text-ink-muted">
                  {data.decision_reason}
                </div>
                <GroupLabel>Supporting evidence</GroupLabel>
                <ConditionList
                  items={data.bullish_evidence}
                  empty="No bullish evidence was verified."
                />
                <GroupLabel>Conflicting evidence</GroupLabel>
                <ConditionList
                  items={data.bearish_evidence}
                  empty="No bearish evidence was verified."
                />
                <GroupLabel>Remaining uncertainty</GroupLabel>
                <ConditionList
                  items={data.warnings.slice(0, 4)}
                  empty="No explicit warning was emitted; the setup still has execution disabled."
                />
                {data.unavailable_fields.length > 0 && (
                  <p className="border-t border-line-soft/70 px-3 py-2 text-[8.5px] leading-relaxed text-ink-faint">
                    Unavailable: {data.unavailable_fields.join(", ")}
                  </p>
                )}
              </Panel>

              <ForecastPanel data={data} />

              <Panel title="Data and model health" icon={<Activity className="size-3.5" />} bodyClassName="p-0">
                <DataRow label="Market state" value={String(data.data_freshness.market_is_stale ? "STALE" : "FRESH")} toneClassName={data.data_freshness.market_is_stale ? "text-warn" : "text-bull"} />
                <DataRow label="Market age" value={`${Math.max(0, Math.round(Number(data.data_freshness.market_age_seconds ?? 0)))} s`} />
                <DataRow label="PATRON" value={data.model_versions.patron ?? "Unavailable"} />
                <DataRow label="Market feature" value={data.model_versions.market_feature ?? "—"} />
                <DataRow label="Strategy" value={data.model_versions.strategy ?? "—"} />
                <DataRow label="Qwen" value={data.ai_status.used ? data.ai_status.model ?? "USED" : data.ai_status.status} />
                <DataRow label="Qwen latency" value={data.ai_status.latency_ms ? `${data.ai_status.latency_ms.toFixed(0)} ms` : "—"} />
                <DataRow label="Position size" value={data.position_size_status} />
                <DataRow label="Execution" value={data.execution} />
                <p className="px-3 py-2 text-[8.5px] leading-relaxed text-ink-faint">{data.disclaimer}</p>
              </Panel>
            </>
          )}
        </aside>
      </div>
    </div>
  );
}
