import type {
  Candle,
  ChartLevelView,
  MarketIntelligence,
  MarketScenario,
  ScenarioId,
  UnifiedTradePlan,
} from "@/lib/types";

const BAR_SECONDS = 900;
const FUTURE_BARS = 6;

export type OverlayTone =
  | "entry"
  | "risk"
  | "target"
  | "confirmation"
  | "support"
  | "resistance"
  | "liquidity"
  | "forecast"
  | "scenario";

export interface OverlayLine {
  id: string;
  label: string;
  price: number;
  tone: OverlayTone;
  dashed?: boolean;
  detail: string;
}

export interface OverlayBand {
  id: string;
  label: string;
  lower: number;
  upper: number;
  tone: "entry" | "risk" | "reward" | "forecast";
  detail: string;
}

export interface OverlayMarker {
  id: string;
  time: number;
  price: number;
  kind: string;
  label: string;
  direction: "BULLISH" | "BEARISH" | "NEUTRAL";
  detail: string;
}

export interface OverlayPath {
  id: string;
  label: string;
  tone: OverlayTone;
  points: Array<{ time: number; price: number }>;
}

export interface OverlayCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface OverlayAnnotation {
  id: string;
  group: "trade" | "structure" | "scenario" | "forecast";
  label: string;
  detail: string;
}

export interface TradeChartOverlay {
  lines: OverlayLine[];
  bands: OverlayBand[];
  markers: OverlayMarker[];
  paths: OverlayPath[];
  predictedCandles: OverlayCandle[];
  annotations: OverlayAnnotation[];
}

export interface OverlayLayers {
  trade: boolean;
  levels: boolean;
  structure: boolean;
  scenarios: boolean;
  forecast: boolean;
  riskReward: boolean;
}

export const DEFAULT_OVERLAY_LAYERS: OverlayLayers = {
  trade: true,
  levels: true,
  structure: true,
  scenarios: false,
  forecast: true,
  riskReward: true,
};

export function parsePrice(value: string | null | undefined): number | null {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function epoch(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const parsed = Date.parse(iso);
  return Number.isFinite(parsed) ? Math.floor(parsed / 1000) : null;
}

function planLines(plan: UnifiedTradePlan | null): OverlayLine[] {
  if (!plan) return [];
  const entry = parsePrice(plan.suggested_entry);
  const lower = parsePrice(plan.entry_zone.lower);
  const upper = parsePrice(plan.entry_zone.upper);
  const stop = parsePrice(plan.stop_loss);
  const confirmation = parsePrice(plan.confirmation_level);
  const lines: OverlayLine[] = [];
  if (lower !== null && upper !== null) {
    lines.push(
      {
        id: "entry-zone-lower",
        label: "Entry zone",
        price: lower,
        tone: "entry",
        detail: `Lower boundary of the deterministic entry zone (${plan.entry_zone.anchor_type.replaceAll("_", " ")}).`,
      },
      {
        id: "entry-zone-upper",
        label: "Entry zone",
        price: upper,
        tone: "entry",
        detail: `Upper boundary of the deterministic entry zone (${plan.entry_zone.anchor_type.replaceAll("_", " ")}).`,
      },
    );
  }
  if (entry !== null) {
    lines.push({
      id: "suggested-entry",
      label: "ENTRY",
      price: entry,
      tone: "entry",
      detail: `Suggested entry from the planning engine (${plan.strategy_id} v${plan.strategy_version}).`,
    });
  }
  if (confirmation !== null) {
    lines.push({
      id: "confirmation-level",
      label: "CONFIRM",
      price: confirmation,
      tone: "confirmation",
      dashed: true,
      detail: "Entry-zone boundary. Confirmation also depends on the listed rule requirements.",
    });
  }
  if (stop !== null) {
    lines.push({
      id: "stop-loss",
      label: "SL",
      price: stop,
      tone: "risk",
      dashed: true,
      detail: plan.stop_basis || "Structural stop from the risk engine.",
    });
  }
  for (const [index, target] of plan.take_profits.entries()) {
    const price = parsePrice(target.price);
    if (price === null) continue;
    lines.push({
      id: `target-${index + 1}`,
      label: target.label || `TP${index + 1}`,
      price,
      tone: "target",
      detail: `${target.label || `TP${index + 1}`} · ${target.method || "deterministic target"} · ${Number(target.risk_multiple).toFixed(2)}R.`,
    });
  }
  return lines;
}

function levelLines(levels: ChartLevelView[]): OverlayLine[] {
  return levels.map((level) => ({
    id: level.id,
    label:
      level.kind === "SUPPORT"
        ? "SUPPORT"
        : level.kind === "RESISTANCE"
          ? "RESISTANCE"
          : "LIQUIDITY",
    price: level.price,
    tone:
      level.kind === "SUPPORT"
        ? "support"
        : level.kind === "RESISTANCE"
          ? "resistance"
          : "liquidity",
    dashed: true,
    detail: level.detail,
  }));
}

function planBands(plan: UnifiedTradePlan | null, showRiskReward: boolean): OverlayBand[] {
  if (!plan) return [];
  const lower = parsePrice(plan.entry_zone.lower);
  const upper = parsePrice(plan.entry_zone.upper);
  const entry = parsePrice(plan.suggested_entry);
  const stop = parsePrice(plan.stop_loss);
  const lastTarget = parsePrice(plan.take_profits.at(-1)?.price);
  const bands: OverlayBand[] = [];
  if (lower !== null && upper !== null) {
    bands.push({
      id: "entry-band",
      label: "Entry zone",
      lower,
      upper,
      tone: "entry",
      detail: "Deterministic entry zone; price is not guaranteed to reach it.",
    });
  }
  if (showRiskReward && entry !== null && stop !== null) {
    bands.push({
      id: "risk-band",
      label: "Risk",
      lower: Math.min(entry, stop),
      upper: Math.max(entry, stop),
      tone: "risk",
      detail: `Planned risk from entry to stop (${plan.stop_basis || "structural stop"}).`,
    });
  }
  if (showRiskReward && entry !== null && lastTarget !== null) {
    bands.push({
      id: "reward-band",
      label: "Reward",
      lower: Math.min(entry, lastTarget),
      upper: Math.max(entry, lastTarget),
      tone: "reward",
      detail: "Planned reward from entry to the final deterministic target.",
    });
  }
  return bands;
}

function forecastPath(intelligence: MarketIntelligence, lastTime: number | null): OverlayPath[] {
  const source = intelligence.forecast_source;
  const reference = source?.reference_close;
  if (
    intelligence.forecast_assessment.status === "STALE" ||
    intelligence.forecast_assessment.status === "INVALID" ||
    intelligence.forecast_assessment.status === "UNAVAILABLE"
  ) {
    return [];
  }
  if (!reference || reference <= 0 || !source?.range_quantiles.length) return [];
  const start = epoch(source.input_last_bar_at) ?? lastTime;
  if (start === null) return [];
  const points = [{ time: start, price: reference }];
  source.range_quantiles.forEach((step, index) => {
    const close = step.close?.q50;
    if (!Number.isFinite(close)) return;
    points.push({
      time: start + (step.step || index + 1) * BAR_SECONDS,
      price: reference * (1 + close),
    });
  });
  return points.length > 1
    ? [
        {
          id: "patron-median",
          label: "PATRON median",
          tone: "forecast",
          points,
        },
      ]
    : [];
}

function forecastCandles(
  intelligence: MarketIntelligence,
  lastTime: number | null,
): OverlayCandle[] {
  const source = intelligence.forecast_source;
  if (
    intelligence.forecast_assessment.status === "STALE" ||
    intelligence.forecast_assessment.status === "INVALID" ||
    intelligence.forecast_assessment.status === "UNAVAILABLE"
  ) {
    return [];
  }
  if (!source || !source.predicted_candles.length) return [];
  const start = epoch(source.input_last_bar_at) ?? lastTime;
  if (start === null) return [];
  return source.predicted_candles
    .map((candle) => ({
      time: Number(candle.timestamp_utc),
      open: Number(candle.open),
      high: Number(candle.high),
      low: Number(candle.low),
      close: Number(candle.close),
    }))
    .filter(
      (candle) =>
        candle.time >= start &&
        [candle.open, candle.high, candle.low, candle.close].every(Number.isFinite),
    )
    .sort((left, right) => left.time - right.time);
}

function scenarioPaths(
  scenarios: MarketScenario[],
  lastTime: number | null,
  lastPrice: number | null,
  focus: ScenarioId | null,
): OverlayPath[] {
  if (lastTime === null || lastPrice === null) return [];
  return scenarios
    .filter(
      (scenario) =>
        scenario.available &&
        scenario.path.length > 0 &&
        (focus === null || scenario.id === focus),
    )
    .map((scenario) => ({
      id: `scenario-${scenario.id}`,
      label: scenario.title,
      tone: "scenario" as const,
      points: [
        { time: lastTime, price: lastPrice },
        ...scenario.path.slice(0, FUTURE_BARS).map((point) => ({
          time: lastTime + point.offset_bars * BAR_SECONDS,
          price: point.price,
        })),
      ],
    }));
}

function structureMarkers(
  intelligence: MarketIntelligence,
  firstTime: number | null,
  lastTime: number | null,
): OverlayMarker[] {
  if (firstTime === null || lastTime === null) return [];
  return intelligence.chart_overlay.structure
    .map((marker) => {
      const time = epoch(marker.time);
      return time === null
        ? null
        : {
            id: marker.id,
            time,
            price: marker.price,
            kind: marker.kind,
            label: marker.label,
            direction: marker.direction,
            detail: marker.detail,
          };
    })
    .filter(
      (marker): marker is OverlayMarker =>
        marker !== null && marker.time >= firstTime && marker.time <= lastTime,
    );
}

export function buildTradeChartOverlay(
  intelligence: MarketIntelligence,
  candles: Candle[],
  layers: OverlayLayers,
  focusedScenario: ScenarioId | null = null,
): TradeChartOverlay {
  const last = candles.at(-1) ?? null;
  const lastTime = last?.time ?? null;
  const lastPrice = last?.close ?? null;
  const lines: OverlayLine[] = [];
  const bands: OverlayBand[] = [];
  const paths: OverlayPath[] = [];
  const predictedCandles: OverlayCandle[] = [];
  const annotations: OverlayAnnotation[] = [];

  if (layers.trade) {
    const tradeLines = planLines(intelligence.trade_plan);
    lines.push(...tradeLines);
    for (const line of tradeLines) {
      annotations.push({
        id: line.id,
        group: "trade",
        label: `${line.label} · ${line.price.toFixed(2)}`,
        detail: line.detail,
      });
    }
    const tradeBands = planBands(intelligence.trade_plan, layers.riskReward);
    bands.push(...tradeBands);
    for (const band of tradeBands) {
      annotations.push({
        id: band.id,
        group: "trade",
        label: `${band.label} · ${band.lower.toFixed(2)} – ${band.upper.toFixed(2)}`,
        detail: band.detail,
      });
    }
  }

  if (layers.levels) {
    const structural = levelLines(intelligence.chart_overlay.levels);
    lines.push(...structural);
    for (const line of structural) {
      annotations.push({
        id: line.id,
        group: "structure",
        label: `${line.label} · ${line.price.toFixed(2)}`,
        detail: line.detail,
      });
    }
  }

  const forecast = layers.forecast ? forecastPath(intelligence, lastTime) : [];
  paths.push(...forecast);
  if (layers.forecast) predictedCandles.push(...forecastCandles(intelligence, lastTime));
  if (forecast.length || predictedCandles.length) {
    annotations.push({
      id: "patron-median",
      group: "forecast",
      label: forecast.length ? "PATRON median path" : "PATRON predicted candles",
      detail:
        "Stored PATRON predicted candles (ghosted) and median close path. Neither is realised market data.",
    });
  }

  if (layers.scenarios) {
    const scenarios = scenarioPaths(
      intelligence.chart_overlay.scenarios,
      lastTime,
      lastPrice,
      focusedScenario,
    );
    paths.push(...scenarios);
    for (const scenario of intelligence.chart_overlay.scenarios.filter(
      (item) =>
        item.available && (focusedScenario === null || item.id === focusedScenario),
    )) {
      annotations.push({
        id: `scenario-${scenario.id}`,
        group: "scenario",
        label: scenario.title,
        detail: `${scenario.condition} Confirmation: ${scenario.confirmation} Invalidation: ${scenario.invalidation_text}`,
      });
    }
  }

  const markers = layers.structure
    ? structureMarkers(intelligence, candles[0]?.time ?? null, lastTime)
    : [];

  return { lines, bands, markers, paths, predictedCandles, annotations };
}

export function toggleLayer(
  current: OverlayLayers,
  key: keyof OverlayLayers,
): OverlayLayers {
  return { ...current, [key]: !current[key] };
}
