type Tone = "bull" | "bear" | "warn" | "neutral";

export interface Reading {
  tone: Tone;
  label: string;
  detail: string;
}

const numeric = (value: number | null | undefined): value is number =>
  typeof value === "number" && Number.isFinite(value);

export function emaStructure(latest: Record<string, number | null>): Reading {
  const { ema9, ema21, ema50 } = latest;
  if (!numeric(ema9) || !numeric(ema21) || !numeric(ema50)) {
    return { tone: "neutral", label: "Warming up", detail: "EMA values unavailable" };
  }
  if (ema9 > ema21 && ema21 > ema50) {
    return { tone: "bull", label: "Bullish stack", detail: "EMA 9 > 21 > 50" };
  }
  if (ema9 < ema21 && ema21 < ema50) {
    return { tone: "bear", label: "Bearish stack", detail: "EMA 9 < 21 < 50" };
  }
  return { tone: "neutral", label: "Compressed", detail: "Moving averages interleaved" };
}

export function rsiState(value: number | null | undefined): Reading {
  if (!numeric(value)) return { tone: "neutral", label: "—", detail: "RSI unavailable" };
  if (value >= 70) return { tone: "warn", label: "Overbought", detail: `${value.toFixed(1)} · caution` };
  if (value <= 30) return { tone: "warn", label: "Oversold", detail: `${value.toFixed(1)} · caution` };
  if (value >= 55) return { tone: "bull", label: "Positive", detail: `${value.toFixed(1)} · above mid` };
  if (value <= 45) return { tone: "bear", label: "Negative", detail: `${value.toFixed(1)} · below mid` };
  return { tone: "neutral", label: "Neutral", detail: `${value.toFixed(1)} · at mid` };
}

export function macdState(value: number | null | undefined): Reading {
  if (!numeric(value)) return { tone: "neutral", label: "—", detail: "MACD unavailable" };
  return value >= 0
    ? { tone: "bull", label: "Above zero", detail: value.toFixed(2) }
    : { tone: "bear", label: "Below zero", detail: value.toFixed(2) };
}

export function bollingerPosition(latest: Record<string, number | null>): number | null {
  const { close, bb_upper, bb_lower } = latest;
  if (!numeric(close) || !numeric(bb_upper) || !numeric(bb_lower)) return null;
  if (bb_upper === bb_lower) return null;
  const ratio = ((close - bb_lower) / (bb_upper - bb_lower)) * 100;
  return Math.max(0, Math.min(100, ratio));
}

export const TONE_TEXT: Record<Tone, string> = {
  bull: "text-bull",
  bear: "text-bear",
  warn: "text-warn",
  neutral: "text-ink-muted",
};

export const TONE_DOT: Record<Tone, string> = {
  bull: "bg-bull",
  bear: "bg-bear",
  warn: "bg-warn",
  neutral: "bg-ink-faint",
};
