import type { ForecastRun, Signal } from "@/lib/types";

/** Percentage-point gap from a 50/50 split used to describe signal strength. */
export const SIGNAL_STRENGTH_THRESHOLDS = {
  balanced: 4,
  moderate: 15,
  strong: 30,
} as const;

export type SignalStrength = "balanced" | "moderate" | "strong" | "dominant";

export interface SignalDistributionData {
  buy: number;
  sell: number;
  source: "patron" | "rules";
  title: string;
  sourceLabel: string;
  strength: SignalStrength;
  strengthLabel: string;
  interpretation: string;
  fresh: boolean;
  freshnessLabel: string;
  updatedAt: string | null;
  confidence: number | null;
  ruleScore: number | null;
  ruleLabel: string | null;
  engine: string | null;
  sourceBars: number | null;
  classProbabilities: Record<string, number> | null;
  barrierProbabilities: { tp_first: number; sl_first: number; timeout: number } | null;
  forecastId: string | null;
  modelId: string | null;
  aiNote: string | null;
  derivation: string;
}

const PATRON_STALE_AFTER_MINUTES = 35;

const PATRON_QUANTILE_DERIVATION =
  "BUY = the model-implied probability that the final 90m close is above the reference close, interpolated monotonically from PATRON's q10/q50/q90 close quantiles; SELL is its complement. It is not a calibrated trade probability.";

const PATRON_MOMENTUM_DERIVATION =
  "Fallback: BUY = strong bullish + bullish + half of sideways; SELL = strong bearish + bearish + half of sideways. Shares are the model's five-class momentum softmax, not a calibrated trade probability.";

const RULES_DERIVATION =
  "BUY = (score + 1) / 2, SELL = 100 − BUY. The underlying score is a directional technical bias in [-1, +1], not a calibrated probability.";

const PATRON_NOTE =
  "Derived from PATRON's quantile head. Treat this as model bias, not a trade signal.";

function roundShare(value: number): number {
  const clamped = Math.max(0, Math.min(100, value));
  return Math.round(clamped * 10) / 10;
}

function strengthFor(gap: number): { level: SignalStrength; label: string } {
  if (gap < SIGNAL_STRENGTH_THRESHOLDS.balanced) {
    return { level: "balanced", label: "Balanced" };
  }
  if (gap < SIGNAL_STRENGTH_THRESHOLDS.moderate) {
    return { level: "moderate", label: "Moderate" };
  }
  if (gap < SIGNAL_STRENGTH_THRESHOLDS.strong) {
    return { level: "strong", label: "Strong" };
  }
  return { level: "dominant", label: "Dominant" };
}

function interpretationFor(buy: number, sell: number, level: SignalStrength): string {
  if (level === "balanced") return "Market direction is relatively balanced.";
  const lead = buy >= sell ? "BUY" : "SELL";
  const trail = buy >= sell ? "SELL" : "BUY";
  if (level === "moderate") {
    return `${lead} pressure is slightly stronger than ${trail} pressure.`;
  }
  if (level === "strong") {
    return `${lead} pressure is stronger than ${trail} pressure.`;
  }
  return `${lead} pressure is dominant; ${trail} pressure is limited.`;
}

function momentumShare(probabilities: Record<string, number>): {
  buy: number;
  sell: number;
  normalized: Record<string, number>;
  confidence: number;
} | null {
  const normalized: Record<string, number> = {};
  let total = 0;
  for (const [key, value] of Object.entries(probabilities)) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric) || numeric < 0) continue;
    normalized[key] = numeric;
    total += numeric;
  }
  if (total <= 0) return null;
  for (const key of Object.keys(normalized)) normalized[key] /= total;

  const bullish = (normalized.strong_bullish ?? 0) + (normalized.bullish ?? 0);
  const sideways = (normalized.sideways ?? 0) + (normalized.neutral ?? 0);
  const buy = roundShare((bullish + sideways / 2) * 100);
  const sell = roundShare(100 - buy);
  const confidence = Math.max(...Object.values(normalized)) * 100;
  return { buy, sell, normalized, confidence };
}

function quantileShare(forecast: ForecastRun): {
  buy: number;
  sell: number;
  confidence: null;
} | null {
  const steps = forecast.output?.patron?.range_quantiles;
  if (!steps?.length) return null;
  const step = [...steps].sort((left, right) => left.step - right.step).at(-1);
  if (!step) return null;
  const { q10, q50, q90 } = step.close;
  if (![q10, q50, q90].every((value) => Number.isFinite(value))) return null;

  // Piecewise-linear inverse CDF through the 10th, 50th and 90th percentile
  // returns. P(close > reference) is the complement of the CDF at zero.
  let cdf: number;
  if (q10 >= 0) {
    cdf = 0;
  } else if (q90 <= 0) {
    cdf = 1;
  } else if (q50 === 0) {
    cdf = 0.5;
  } else if (q50 > 0) {
    cdf = 0.1 + ((0 - q10) / (q50 - q10)) * 0.4;
  } else {
    cdf = 0.5 + ((0 - q50) / (q90 - q50)) * 0.4;
  }
  const buy = roundShare((1 - cdf) * 100);
  return { buy, sell: roundShare(100 - buy), confidence: null };
}

function patronData(
  forecast: ForecastRun,
  shares: {
    buy: number;
    sell: number;
    confidence: number | null;
    normalized?: Record<string, number>;
  },
  fresh: boolean,
  basis: "quantiles" | "momentum",
): SignalDistributionData {
  const gap = Math.abs(shares.buy - shares.sell);
  const strength = strengthFor(gap);
  return {
    buy: shares.buy,
    sell: shares.sell,
    source: "patron",
    title: "Model bias distribution",
    sourceLabel: basis === "quantiles" ? "PATRON 90m close path" : "PATRON momentum head",
    strength: strength.level,
    strengthLabel: strength.label,
    interpretation: interpretationFor(shares.buy, shares.sell, strength.level),
    fresh,
    freshnessLabel: fresh ? "Live" : "Stale forecast",
    updatedAt: forecast.created_at,
    confidence: shares.confidence,
    ruleScore: null,
    ruleLabel: null,
    engine: forecast.model_id,
    sourceBars: forecast.input_candle_count,
    classProbabilities: basis === "momentum" ? (shares.normalized ?? null) : null,
    barrierProbabilities: forecast.output?.patron?.barrier_probabilities ?? null,
    forecastId: forecast.id,
    modelId: forecast.model_id,
    aiNote: PATRON_NOTE,
    derivation: basis === "quantiles" ? PATRON_QUANTILE_DERIVATION : PATRON_MOMENTUM_DERIVATION,
  };
}

/**
 * Derive a BUY/SELL split from real model output.
 *
 * PATRON's five-class momentum softmax is used when it is fresh; sideways mass is
 * split evenly between both sides. If no fresh PATRON forecast exists, the
 * existing rule-engine directional score is mapped linearly from [-1, +1] to
 * [0%, 100%]. That fallback is directional strength, not a probability, and the
 * component labels it accordingly. No random or default split is ever used.
 */
export function buildSignalDistribution(
  signal: Signal | null,
  forecast: ForecastRun | null,
  now: number = Date.now(),
): SignalDistributionData | null {
  const probabilities = forecast?.output?.patron?.momentum?.class_probabilities ?? null;
  const momentum = probabilities ? momentumShare(probabilities) : null;
  const quantiles = forecast ? quantileShare(forecast) : null;
  const shares = quantiles ?? momentum;
  const basis = quantiles ? "quantiles" : "momentum";

  const createdMs = forecast?.created_at ? Date.parse(forecast.created_at) : Number.NaN;
  const ageMinutes = Number.isFinite(createdMs) ? (now - createdMs) / 60_000 : null;
  const patronFresh =
    Boolean(shares) &&
    forecast?.status === "ok" &&
    ageMinutes !== null &&
    ageMinutes >= -1 &&
    ageMinutes <= PATRON_STALE_AFTER_MINUTES;

  const ruleUnavailable = signal?.freshness?.toLowerCase() === "unavailable";
  const ruleScore =
    signal && !ruleUnavailable && Number.isFinite(signal.score)
      ? Math.max(-1, Math.min(1, signal.score))
      : null;
  const ruleAvailable = ruleScore !== null;
  const ruleFresh = ruleAvailable && signal?.freshness?.toLowerCase() === "fresh";

  // Prefer fresh PATRON output. Fall back to the rule engine when it is the
  // only fresh source, and only then show stale PATRON output.
  if (shares && forecast && (patronFresh || !ruleAvailable)) {
    return patronData(forecast, shares, patronFresh, basis);
  }

  if (ruleAvailable && signal) {
    const buy = roundShare(((ruleScore + 1) / 2) * 100);
    const sell = roundShare(100 - buy);
    const gap = Math.abs(buy - sell);
    const strength = strengthFor(gap);
    return {
      buy,
      sell,
      source: "rules",
      title: "Directional signal strength",
      sourceLabel: "Rule engine",
      strength: strength.level,
      strengthLabel: strength.label,
      interpretation: interpretationFor(buy, sell, strength.level),
      fresh: ruleFresh,
      freshnessLabel: ruleFresh ? "Live" : "Stale reading",
      updatedAt: signal.generated_at ?? null,
      confidence: null,
      ruleScore,
      ruleLabel: signal.label ?? null,
      engine: signal.engine ?? null,
      sourceBars: signal.source_candle_count ?? null,
      classProbabilities: null,
      barrierProbabilities: null,
      forecastId: null,
      modelId: null,
      aiNote: signal.ai_note ?? null,
      derivation: RULES_DERIVATION,
    };
  }

  if (shares && forecast) {
    return patronData(forecast, shares, false, basis);
  }

  return null;
}
