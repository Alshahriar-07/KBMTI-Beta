import { AlertTriangle, Bot, GaugeCircle } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { formatTimeOnly } from "@/lib/format";
import type { ForecastAssessmentStatus, MarketIntelligence } from "@/lib/types";
import { cn } from "@/lib/utils";

const ASSESSMENT_TONE: Record<
  ForecastAssessmentStatus,
  "success" | "warning" | "danger" | "muted"
> = {
  VALID: "success",
  LOW_CONFIDENCE: "warning",
  CONFLICTING_EVIDENCE: "danger",
  STALE: "warning",
  INVALID: "danger",
  UNAVAILABLE: "muted",
};

const AI_TONE: Record<string, "info" | "warning" | "danger" | "muted"> = {
  USED: "info",
  INITIALIZING: "info",
  INITIALIZATION_TIMEOUT: "warning",
  UNAVAILABLE: "muted",
  INVALID: "danger",
  TIMEOUT: "warning",
  DISABLED: "muted",
};

function DecisionBadge({ decision }: { decision: MarketIntelligence["decision"] }) {
  const tone =
    decision === "LONG" ? "success" : decision === "SHORT" ? "danger" : decision === "WAIT" ? "warning" : "muted";
  return (
    <Badge tone={tone} dot>
      {decision}
    </Badge>
  );
}

function EvidenceList({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: "bull" | "bear";
}) {
  return (
    <div className="min-w-0">
      <p className={cn("text-[8.5px] font-medium", tone === "bull" ? "text-bull" : "text-bear")}>
        {title}
      </p>
      {items.length ? (
        <ul className="mt-1 space-y-1">
          {items.slice(0, 3).map((item) => (
            <li key={item} className="text-[9px] leading-snug text-ink-faint">
              {item}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-[9px] text-ink-faint">No deterministic evidence.</p>
      )}
    </div>
  );
}

/**
 * One shared, validated response replaces per-component PATRON interpretation.
 * Loading, missing, stale and AI-failure states are explicit; nothing is filled
 * with a fabricated fallback value.
 */
export function AiIntelligencePanel({
  intelligence,
  loading = false,
  error = null,
}: {
  intelligence: MarketIntelligence | null;
  loading?: boolean;
  error?: string | null;
}) {
  return (
    <section className="border-b border-line-soft bg-surface-2/20 px-3 py-2.5">
      <header className="flex items-center gap-1.5">
        <Bot className="size-3.5 text-primary" aria-hidden />
        <span className="label-xs text-[10px]">AI market intelligence</span>
        {intelligence && (
          <Badge tone={AI_TONE[intelligence.ai_status.status] ?? "muted"} className="ml-auto">
            {intelligence.ai_status.status}
          </Badge>
        )}
        {loading && !intelligence && <Spinner className="ml-auto" />}
      </header>

      {!intelligence && (
        <div className="mt-2 rounded-[6px] border border-dashed border-line-soft px-2 py-2 text-[9.5px] leading-relaxed text-ink-faint">
          {loading ? (
            "Building the unified market and forecast assessment…"
          ) : (
            <>
              Unified intelligence is unavailable
              {error ? `: ${error}` : "."} Deterministic market data and risk checks remain
              independent; no PATRON output is shown as a final decision.
            </>
          )}
        </div>
      )}

      {intelligence && (
        <>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <DecisionBadge decision={intelligence.decision} />
            <Badge tone={ASSESSMENT_TONE[intelligence.forecast_assessment.status]}>
              Forecast {intelligence.forecast_assessment.status.replaceAll("_", " ").toLowerCase()}
            </Badge>
            {intelligence.forecast_assessment.usable_in_decision ? (
              <Badge tone="info">usable as evidence</Badge>
            ) : (
              <Badge tone="warning">excluded from decision</Badge>
            )}
            {intelligence.is_stale && <Badge tone="warning">market stale</Badge>}
          </div>

          <p className="mt-2 text-[10px] leading-relaxed text-ink-muted">
            {intelligence.ai_market_interpretation}
          </p>
          <p className="mt-1.5 flex gap-1.5 text-[9.5px] leading-relaxed text-ink-faint">
            <GaugeCircle className="mt-[1px] size-3 shrink-0 text-primary/70" aria-hidden />
            <span>{intelligence.ai_forecast_interpretation}</span>
          </p>

          {intelligence.forecast_assessment.reasons.length > 0 && (
            <ul className="mt-1.5 space-y-0.5">
              {intelligence.forecast_assessment.reasons.slice(0, 3).map((reason) => (
                <li key={reason} className="text-[9px] leading-snug text-ink-faint">
                  · {reason}
                </li>
              ))}
            </ul>
          )}

          {!intelligence.ai_status.used && intelligence.ai_status.error && (
            <p className="mt-1.5 text-[9px] leading-snug text-warn/90">
              AI {intelligence.ai_status.status.toLowerCase()}: {intelligence.ai_status.error}
            </p>
          )}

          <div className="mt-2 grid grid-cols-2 gap-2 border-t border-line-soft/70 pt-1.5">
            <EvidenceList title="Bullish evidence" items={intelligence.bullish_evidence} tone="bull" />
            <EvidenceList title="Bearish evidence" items={intelligence.bearish_evidence} tone="bear" />
          </div>

          {(intelligence.warnings.length > 0 || intelligence.unavailable_fields.length > 0) && (
            <div className="mt-2 border-t border-line-soft/70 pt-1.5">
              {intelligence.warnings.slice(0, 2).map((warning) => (
                <p
                  key={warning}
                  className="flex gap-1 text-[9px] leading-snug text-warn/90"
                >
                  <AlertTriangle className="mt-[1px] size-2.5 shrink-0" aria-hidden />
                  <span>{warning}</span>
                </p>
              ))}
              {intelligence.unavailable_fields.length > 0 && (
                <p className="mt-1 text-[8.5px] text-ink-faint">
                  Unavailable: {intelligence.unavailable_fields.join(", ")}
                </p>
              )}
            </div>
          )}

          <p className="mt-2 flex items-center justify-between gap-2 border-t border-line-soft/70 pt-1.5 text-[8.5px] text-ink-faint">
            <span>
              PATRON {intelligence.forecast_source?.model_version ?? "unavailable"} · source evidence
            </span>
            <span className="num">
              {intelligence.ai_status.used
                ? `${intelligence.ai_status.latency_ms?.toFixed(0) ?? "—"} ms`
                : `deterministic · ${formatTimeOnly(intelligence.generated_at)}`}
            </span>
          </p>
        </>
      )}
    </section>
  );
}
