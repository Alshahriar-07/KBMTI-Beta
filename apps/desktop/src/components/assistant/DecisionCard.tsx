import { ShieldAlert } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import type { TradingIntelligence } from "@/lib/types";
import { cn } from "@/lib/utils";

const ACTION_STYLE: Record<TradingIntelligence["action"], string> = {
  LONG: "border-bull/30 bg-bull/[0.06] text-bull",
  SHORT: "border-bear/30 bg-bear/[0.06] text-bear",
  WAIT: "border-warn/30 bg-warn/[0.05] text-warn",
  NO_TRADE: "border-line-strong bg-surface-2/60 text-ink-muted",
};

export function DecisionCard({ data }: { data: TradingIntelligence }) {
  return (
    <section className={cn("rounded-[10px] border p-3", ACTION_STYLE[data.action])}>
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-[9.5px] font-medium tracking-[0.08em] text-ink-faint">
            DETERMINISTIC DECISION
          </p>
          <p className="mt-1 text-[24px] font-semibold leading-none tracking-[0.02em]">
            {data.action.replace("_", " ")}
          </p>
          <p className="mt-1.5 text-[10.5px] leading-relaxed text-ink-muted">
            {data.next_action}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <Badge tone="warning" dot>
            {data.plan_status}
          </Badge>
          <Badge tone="info">{data.execution_eligibility}</Badge>
          <Badge tone="muted">Strategy {data.strategy_validation_status}</Badge>
        </div>
      </div>
      <div className="mt-3 flex items-start gap-1.5 border-t border-current/10 pt-2 text-[9.5px] leading-relaxed text-ink-faint">
        <ShieldAlert className="mt-[1px] size-3 shrink-0" aria-hidden />
        <p>
          {data.execution} · position size {data.position_size_status} · no order exists.
          {data.is_stale ? " Market data is stale." : ""}
        </p>
      </div>
    </section>
  );
}
