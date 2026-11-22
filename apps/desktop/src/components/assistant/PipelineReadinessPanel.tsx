import { ListChecks } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { Panel } from "@/components/ui/Panel";
import { readinessTone } from "@/lib/readiness";
import type { ComponentReadiness, PipelineReadiness } from "@/lib/types";

const ROWS: Array<{ key: keyof PipelineReadiness; label: string }> = [
  { key: "market", label: "Market analysis" },
  { key: "patron", label: "PATRON forecast" },
  { key: "qwen", label: "Qwen interpretation" },
  { key: "strategy", label: "Strategy validation" },
  { key: "trade_plan", label: "Trade plan" },
  { key: "risk", label: "Risk assessment" },
  { key: "position_size", label: "Position size" },
  { key: "execution", label: "Execution" },
];

export function PipelineReadinessPanel({ readiness }: { readiness: PipelineReadiness }) {
  return (
    <Panel
      title="Pipeline readiness"
      icon={<ListChecks className="size-3.5" />}
      meta={
        <span className="text-[8.5px] text-ink-faint">
          each component reports its own state
        </span>
      }
      bodyClassName="p-0"
    >
      {ROWS.map(({ key, label }) => {
        const component = readiness[key] as ComponentReadiness;
        return (
          <div
            key={key}
            className="border-t border-line-soft/70 px-3 py-2 first:border-t-0"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-[9.5px] font-medium text-ink-muted">{label}</span>
              <Badge tone={readinessTone(component.status)}>
                {component.status.replaceAll("_", " ")}
              </Badge>
            </div>
            <p className="mt-1 text-[8.5px] leading-snug text-ink-faint">
              {component.detail}
            </p>
            {key === "qwen" && readiness.qwen.waited_seconds ? (
              <p className="num mt-0.5 text-[8px] text-ink-faint/80">
                waited {readiness.qwen.waited_seconds.toFixed(2)} s for readiness
              </p>
            ) : null}
            {component.reason_code && (
              <p className="num mt-0.5 text-[8px] text-ink-faint/80">
                reason: {component.reason_code}
              </p>
            )}
            {component.missing_inputs.length > 0 && (
              <p className="mt-0.5 text-[8px] leading-snug text-ink-faint/80">
                missing: {component.missing_inputs.join(", ")}
              </p>
            )}
          </div>
        );
      })}
    </Panel>
  );
}
