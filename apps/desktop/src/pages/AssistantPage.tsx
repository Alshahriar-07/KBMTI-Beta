import { BookOpen, BrainCircuit, Gauge, ShieldAlert } from "lucide-react";

import { DecisionCard } from "@/components/assistant/DecisionCard";
import { Badge } from "@/components/ui/Badge";
import { DataRow } from "@/components/ui/DataRow";
import { EmptyState } from "@/components/ui/EmptyState";
import { GroupLabel, Panel } from "@/components/ui/Panel";
import { Spinner } from "@/components/ui/Spinner";
import { usePolling } from "@/hooks/usePolling";
import { api } from "@/lib/api";
import { formatBrokerTime, formatPrice } from "@/lib/format";
import type { AssistantStatus, PlanningResult, TradingIntelligence } from "@/lib/types";

function price(value: string | null | undefined): string {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? formatPrice(parsed, 2) : "—";
}

export function AssistantPage() {
  const intelligence = usePolling<TradingIntelligence>(
    "assistant-current",
    () => api.assistantCurrent(true),
    20_000,
  );
  const planning = usePolling<PlanningResult>("assistant-planning", () => api.planningCurrent(), 20_000);
  const status = usePolling<AssistantStatus>("assistant-status", () => api.assistantStatus(), 30_000);
  const data = intelligence.data;
  const plan = planning.data?.plan ?? null;

  if (intelligence.loading && !data) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-[10.5px] text-ink-faint">
        <Spinner /> Building deterministic intelligence…
      </div>
    );
  }
  if (!data) {
    return (
      <div className="scroll-area h-full p-4">
        <EmptyState
          icon={BrainCircuit}
          title="Trading intelligence unavailable"
          description={intelligence.error ?? "The assistant endpoint did not return a reading."}
        />
      </div>
    );
  }

  return (
    <div className="scroll-area h-full">
      <div className="border-b border-line bg-surface px-3 py-2.5">
        <div className="mx-auto flex max-w-[1500px] flex-wrap items-center gap-2">
          <span className="label-xs">AI trading assistant</span>
          <Badge tone={data.qwen.used ? "info" : "muted"} dot>
            {data.qwen.used ? `Qwen ${data.qwen.status}` : "Deterministic fallback"}
          </Badge>
          <Badge tone="warning">Gate PENDING</Badge>
          <span className="num ml-auto text-[9.5px] text-ink-faint">
            {data.symbol} · {data.timeframe} · as of {formatBrokerTime(data.data_as_of)}
          </span>
        </div>
      </div>

      <div className="mx-auto grid max-w-[1500px] gap-2 p-2 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 space-y-2">
          <DecisionCard data={data} />

          <div className="grid gap-2 lg:grid-cols-2">
            <Panel title="Market condition" icon={<Gauge className="size-3.5" />} bodyClassName="p-0">
              <div className="px-3 py-3 text-[10.5px] leading-relaxed text-ink-muted">
                {data.market_explanation}
              </div>
            </Panel>

            <Panel title="Strategy comparison" icon={<BrainCircuit className="size-3.5" />} bodyClassName="p-0">
              {data.strategy_comparison.map((strategy) => (
                <div key={strategy.strategy_id} className="border-b border-line-soft/70 px-3 py-2 last:border-b-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-medium text-ink">{strategy.strategy_id}</span>
                    <Badge tone={strategy.decision === "LONG" ? "success" : strategy.decision === "SHORT" ? "danger" : "warning"}>
                      {strategy.decision}
                    </Badge>
                    <span className="num ml-auto text-[9.5px] text-ink-faint">v{strategy.strategy_version}</span>
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-[9.5px] text-ink-faint">
                    <span>Quality {strategy.quality_score}/100 · {strategy.quality_label}</span>
                    <span>·</span>
                    <span>{strategy.validation_status}</span>
                  </div>
                  <p className="mt-1 text-[9.5px] leading-relaxed text-ink-faint">{strategy.reason}</p>
                </div>
              ))}
            </Panel>
          </div>

          <Panel title="Plan, next action and evidence" icon={<ShieldAlert className="size-3.5" />} bodyClassName="p-0">
            <div className="px-3 py-3 text-[10.5px] leading-relaxed text-ink-muted">{data.plan_explanation}</div>
            {plan && (
              <>
                <GroupLabel>Geometry</GroupLabel>
                <div className="grid md:grid-cols-2 md:divide-x md:divide-line">
                  <div>
                    <DataRow label="Entry zone" value={`${price(plan.entry_zone.lower)} – ${price(plan.entry_zone.upper)}`} />
                    <DataRow label="Suggested entry" value={price(plan.suggested_entry)} />
                    <DataRow label="Structural stop" value={price(plan.stop_loss)} toneClassName="text-bear" />
                    <DataRow label="Reference price" value={price(plan.reference_price)} />
                  </div>
                  <div>
                    {plan.take_profits.map((target) => (
                      <DataRow
                        key={target.label}
                        label={`${target.label} · ${target.method}`}
                        value={price(target.price)}
                        hint={`${Number(target.risk_multiple).toFixed(2)}R`}
                        toneClassName="text-bull"
                      />
                    ))}
                    <DataRow
                      label="R:R TP1 / TP2 / TP3"
                      value={`${Number(plan.risk_reward.rr_tp1).toFixed(2)} / ${Number(plan.risk_reward.rr_tp2).toFixed(2)} / ${Number(plan.risk_reward.rr_tp3).toFixed(2)}`}
                    />
                  </div>
                </div>
                <GroupLabel>Invalidation and confirmation</GroupLabel>
                <ul className="space-y-1 px-3 py-2">
                  {[...plan.invalidation_conditions, ...plan.confirmation_requirements].map((line) => (
                    <li key={line} className="flex gap-2 text-[10px] leading-relaxed text-ink-faint">
                      <span className="mt-[6px] size-1 shrink-0 bg-ink-faint/60" />
                      {line}
                    </li>
                  ))}
                </ul>
              </>
            )}
            <GroupLabel>Evidence references</GroupLabel>
            <div className="flex flex-wrap gap-1 px-3 py-2">
              {data.evidence_refs.map((ref) => (
                <span key={ref} className="num max-w-full truncate rounded-[4px] border border-line-soft px-1.5 py-0.5 text-[8.5px] text-ink-faint">
                  {ref}
                </span>
              ))}
            </div>
          </Panel>
        </div>

        <div className="space-y-2">
          <Panel title="Uncertainty" icon={<ShieldAlert className="size-3.5" />} bodyClassName="p-0">
            <p className="px-3 py-3 text-[10.5px] leading-relaxed text-ink-muted">{data.uncertainty}</p>
            <DataRow label="Qwen" value={data.qwen.used ? data.qwen.model ?? "used" : data.qwen.status} />
            <DataRow label="Qwen latency" value={data.qwen.latency_ms ? `${data.qwen.latency_ms.toFixed(0)} ms` : "—"} />
            <DataRow label="Plan id" value={data.plan_id ?? "none"} />
            <DataRow label="Snapshot" value={data.snapshot_id} />
          </Panel>

          <Panel title="Knowledge references" icon={<BookOpen className="size-3.5" />} bodyClassName="p-0">
            {data.knowledge.map((hit) => (
              <div key={hit.id} className="border-b border-line-soft/70 px-3 py-2 last:border-b-0">
                <div className="flex items-center gap-2">
                  <span className="text-[10.5px] font-medium text-ink-muted">{hit.title}</span>
                  <span className="num ml-auto text-[8.5px] text-ink-faint">v{hit.version}</span>
                </div>
                <p className="mt-1 line-clamp-3 text-[9.5px] leading-relaxed text-ink-faint">{hit.text}</p>
              </div>
            ))}
          </Panel>

          <Panel title="Warnings" icon={<ShieldAlert className="size-3.5" />} bodyClassName="p-0">
            <ul className="space-y-1 px-3 py-2">
              {data.warnings.map((warning) => (
                <li key={warning} className="text-[9.5px] leading-relaxed text-warn/80">
                  {warning}
                </li>
              ))}
            </ul>
          </Panel>

          <Panel title="Assistant status" icon={<BrainCircuit className="size-3.5" />} bodyClassName="p-0">
            <DataRow label="Qwen enabled / ready" value={`${status.data?.qwen_enabled ? "yes" : "no"} / ${status.data?.qwen_ready ? "yes" : "no"}`} />
            <DataRow label="Knowledge docs" value={status.data?.knowledge_documents ?? "—"} />
            <DataRow label="Knowledge version" value={status.data?.knowledge_version ?? "—"} />
            <DataRow label="Execution" value="DISABLED" />
          </Panel>
          <p className="px-1 text-[8.5px] leading-relaxed text-ink-faint">{data.disclaimer}</p>
        </div>
      </div>
    </div>
  );
}
